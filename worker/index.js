/**
 * IDS Meeting Bot — Cloudflare Worker
 * Handles: Telegram webhook (commands) + Zoom webhook (recording events)
 *
 * Routes:
 *   POST /telegram  — Telegram bot updates
 *   POST /zoom      — Zoom webhook events
 *   GET  /          — health check
 */

addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request));
});

async function handleRequest(request) {
  const url = new URL(request.url);

  if (request.method === 'GET') {
    return new Response('IDS Meeting Bot ✓', { status: 200 });
  }

  if (request.method === 'POST' && url.pathname === '/telegram') {
    return handleTelegram(request);
  }

  if (request.method === 'POST' && url.pathname === '/zoom') {
    return handleZoom(request);
  }

  return new Response('Not Found', { status: 404 });
}

// ─── TELEGRAM ──────────────────────────────────────────────────────────────

async function handleTelegram(request) {
  let body;
  try { body = await request.json(); } catch { return ok(); }

  const msg = body?.message;
  if (!msg) return ok();

  const chatId = String(msg.chat?.id);
  const text   = msg.text || '';

  // Chỉ cho phép anh Nguyên (chat_id cố định)
  if (chatId !== TELEGRAM_CHAT_ID) {
    await tgSend(chatId, '⛔ Không có quyền truy cập.');
    return ok();
  }

  const lower = text.trim().toLowerCase();

  if (lower.startsWith('/meeting ')) {
    return handleMeetingCommand(chatId, text.slice(9).trim());
  }
  if (lower === '/meetings') {
    return handleListMeetings(chatId);
  }
  if (lower === '/tasks') {
    return handleListTasks(chatId);
  }
  if (lower === '/help') {
    return handleHelp(chatId);
  }

  await tgSend(chatId, '❓ Lệnh không hợp lệ. Gõ /help để xem hướng dẫn.');
  return ok();
}

async function handleHelp(chatId) {
  const msg = `📖 <b>IDS Meeting Bot — Hướng dẫn</b>

<b>Tạo meeting:</b>
<code>/meeting "Tiêu đề" YYYY-MM-DD HH:MM phút email1 email2</code>

<b>Ví dụ:</b>
<code>/meeting "Review Q2 Castrol" 2026-05-10 14:00 60 nam@ids-international.vn lan@ids-international.vn</code>

<b>Xem danh sách meeting sắp tới:</b>
<code>/meetings</code>

<b>Xem action items chưa xong:</b>
<code>/tasks</code>

💡 Pre-read: thêm <code>| tài liệu: https://...</code> vào cuối lệnh`;

  await tgSend(chatId, msg);
  return ok();
}

async function handleMeetingCommand(chatId, args) {
  // Format: "Title" YYYY-MM-DD HH:MM duration_min email1 email2 [| tài liệu: url]
  // Example: "Review Q2" 2026-05-10 14:00 60 a@ids.vn b@ids.vn | tài liệu: https://...

  await tgSend(chatId, '⏳ Đang tạo meeting...');

  try {
    // Split pre-read if any
    let preRead = '';
    let mainPart = args;
    if (args.includes('| tài liệu:')) {
      const parts = args.split('| tài liệu:');
      mainPart = parts[0].trim();
      preRead = parts[1].trim();
    }

    // Parse: "Title" YYYY-MM-DD HH:MM duration emails...
    const titleMatch = mainPart.match(/^"([^"]+)"\s+(.+)$/);
    if (!titleMatch) {
      await tgSend(chatId, '❌ Sai format. Xem /help để biết cách dùng.');
      return ok();
    }

    const title = titleMatch[1];
    const rest  = titleMatch[2].trim().split(/\s+/);

    if (rest.length < 4) {
      await tgSend(chatId, '❌ Thiếu thông tin. Cần: ngày giờ thời-lượng email...');
      return ok();
    }

    const dateStr    = rest[0];            // YYYY-MM-DD
    const timeStr    = rest[1];            // HH:MM
    const duration   = parseInt(rest[2]);  // minutes
    const emails     = rest.slice(3);      // email list

    const startTime  = `${dateStr}T${timeStr}:00`;

    // Get Zoom token
    const zoomToken = await getZoomToken();

    // Create meeting
    const meeting = await createZoomMeeting(zoomToken, title, startTime, duration, emails, preRead);

    // Store in KV for later pipeline lookup
    await MEETINGS_KV.put(`meeting:${meeting.id}`, JSON.stringify({
      id: meeting.id,
      title,
      start_time: startTime,
      duration,
      emails,
      pre_read: preRead,
      created_at: new Date().toISOString()
    }), { expirationTtl: 60 * 60 * 24 * 30 }); // 30 days

    const dt = new Date(`${dateStr}T${timeStr}:00+07:00`);
    const dtStr = dt.toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh',
      weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit' });

    const reply = `✅ <b>Meeting đã tạo!</b>

📌 <b>${title}</b>
📅 ${dtStr}
⏱ ${duration} phút
👥 ${emails.length} người tham gia
${preRead ? `📎 Pre-read: ${preRead}` : ''}

🔗 <a href="${meeting.join_url}">Join Meeting</a>
🆔 Meeting ID: <code>${meeting.id}</code>
🔑 Passcode: <code>${meeting.password || 'Không có'}</code>

📨 Invite đã gửi đến: ${emails.join(', ')}`;

    await tgSend(chatId, reply);

    // Schedule reminder 30 min before
    await scheduleReminder(meeting.id, title, startTime, chatId);

  } catch (err) {
    await tgSend(chatId, `❌ Lỗi tạo meeting: ${err.message}`);
  }

  return ok();
}

async function handleListMeetings(chatId) {
  try {
    const zoomToken = await getZoomToken();
    const r = await fetch('https://api.zoom.us/v2/users/me/meetings?type=upcoming&page_size=5', {
      headers: { 'Authorization': `Bearer ${zoomToken}` }
    });
    const data = await r.json();
    const meetings = data.meetings || [];

    if (!meetings.length) {
      await tgSend(chatId, '📭 Không có meeting nào sắp diễn ra.');
      return ok();
    }

    let msg = '📅 <b>Meeting sắp tới:</b>\n\n';
    for (const m of meetings) {
      const dt = new Date(m.start_time).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' });
      msg += `• <b>${m.topic}</b>\n  ${dt} · ${m.duration} phút\n  🔗 <a href="${m.join_url}">Join</a>\n\n`;
    }
    await tgSend(chatId, msg);
  } catch (err) {
    await tgSend(chatId, `❌ Lỗi: ${err.message}`);
  }
  return ok();
}

async function handleListTasks(chatId) {
  // Trigger GH Actions để lấy tasks từ Google Sheets
  await triggerGitHubActions('list_tasks', { chat_id: chatId });
  await tgSend(chatId, '⏳ Đang lấy danh sách tasks...');
  return ok();
}

// ─── ZOOM WEBHOOK ──────────────────────────────────────────────────────────

async function handleZoom(request) {
  const body = await request.text();
  let payload;
  try { payload = JSON.parse(body); } catch { return ok(); }

  // URL validation (one-time setup)
  if (payload.event === 'endpoint.url_validation') {
    const { plainToken } = payload.payload;
    const hmac = await computeHmac(ZOOM_WEBHOOK_SECRET, plainToken);
    return new Response(JSON.stringify({
      plainToken,
      encryptedToken: hmac
    }), { headers: { 'Content-Type': 'application/json' } });
  }

  // Verify webhook signature
  const signature  = request.headers.get('x-zm-signature') || '';
  const timestamp  = request.headers.get('x-zm-request-timestamp') || '';
  const message    = `v0:${timestamp}:${body}`;
  const expected   = 'v0=' + await computeHmac(ZOOM_WEBHOOK_SECRET, message);

  if (signature !== expected) {
    return new Response('Unauthorized', { status: 401 });
  }

  // Handle recording completed
  if (payload.event === 'recording.completed') {
    const meetingId  = String(payload.payload?.object?.id || payload.payload?.object?.uuid);
    const meetingObj = payload.payload?.object || {};

    // Get stored meeting info from KV
    const stored = await MEETINGS_KV.get(`meeting:${meetingId}`);
    const meetingInfo = stored ? JSON.parse(stored) : null;

    await triggerGitHubActions('process_recording', {
      meeting_id   : meetingId,
      meeting_uuid : meetingObj.uuid,
      topic        : meetingObj.topic || meetingInfo?.title || '',
      start_time   : meetingObj.start_time || meetingInfo?.start_time || '',
      duration     : meetingObj.duration || meetingInfo?.duration || 0,
      emails       : meetingInfo?.emails || [],
      host_email   : meetingObj.host_email || ''
    });
  }

  return ok();
}

// ─── HELPERS ───────────────────────────────────────────────────────────────

async function getZoomToken() {
  const creds = btoa(`${ZOOM_CLIENT_ID}:${ZOOM_CLIENT_SECRET}`);
  const r = await fetch(
    `https://zoom.us/oauth/token?grant_type=account_credentials&account_id=${ZOOM_ACCOUNT_ID}`,
    { method: 'POST', headers: { 'Authorization': `Basic ${creds}` } }
  );
  const data = await r.json();
  if (!data.access_token) throw new Error(`Zoom auth failed: ${JSON.stringify(data)}`);
  return data.access_token;
}

async function createZoomMeeting(token, title, startTime, duration, emails, preRead) {
  const agendaNote = preRead ? `\n\n📎 Tài liệu đọc trước: ${preRead}` : '';
  const r = await fetch('https://api.zoom.us/v2/users/me/meetings', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      topic     : title,
      type      : 2,
      start_time: startTime,
      duration,
      timezone  : 'Asia/Ho_Chi_Minh',
      agenda    : `Cuộc họp IDS${agendaNote}`,
      settings  : {
        auto_recording     : 'cloud',
        audio              : 'both',
        join_before_host   : true,
        waiting_room       : false,
        meeting_invitees   : emails.map(e => ({ email: e })),
        send_invitation    : true
      }
    })
  });
  const data = await r.json();
  if (!data.id) throw new Error(`Create meeting failed: ${JSON.stringify(data)}`);
  return data;
}

async function scheduleReminder(meetingId, title, startTime, chatId) {
  // Store reminder info; GH Actions cron will check and send
  const remindAt = new Date(new Date(startTime + '+07:00').getTime() - 30 * 60 * 1000).toISOString();
  await MEETINGS_KV.put(`reminder:${meetingId}`, JSON.stringify({
    meeting_id: meetingId, title, remind_at: remindAt, chat_id: chatId, sent: false
  }), { expirationTtl: 60 * 60 * 24 * 7 });
}

async function triggerGitHubActions(eventType, payload) {
  const r = await fetch(
    `https://api.github.com/repos/NguyenPhinDeli/zoom-meeting-bot/dispatches`,
    {
      method : 'POST',
      headers: {
        'Authorization': `Bearer ${GH_PAT}`,
        'Accept'       : 'application/vnd.github+json',
        'Content-Type' : 'application/json'
      },
      body: JSON.stringify({ event_type: eventType, client_payload: payload })
    }
  );
  if (!r.ok) {
    const err = await r.text();
    throw new Error(`GH Actions trigger failed: ${err}`);
  }
}

async function tgSend(chatId, text) {
  await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body   : JSON.stringify({
      chat_id                  : chatId,
      text,
      parse_mode               : 'HTML',
      disable_web_page_preview : true
    })
  });
}

async function computeHmac(secret, message) {
  const enc = new TextEncoder();
  const key  = await crypto.subtle.importKey(
    'raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  const sig  = await crypto.subtle.sign('HMAC', key, enc.encode(message));
  return Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function ok() {
  return new Response('OK', { status: 200 });
}
