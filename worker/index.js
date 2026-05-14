/**
 * IDS Meeting Bot — Cloudflare Worker (ES Module)
 * Routes: POST /telegram, POST /zoom, GET /
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'GET') return new Response('IDS Meeting Bot ✓', { status: 200 });
    if (request.method === 'POST' && url.pathname === '/telegram') return handleTelegram(request, env);
    if (request.method === 'POST' && url.pathname === '/zoom')     return handleZoom(request, env);
    return new Response('Not Found', { status: 404 });
  }
};

// ─── TELEGRAM ──────────────────────────────────────────────────────────────

async function handleTelegram(request, env) {
  let body;
  try { body = await request.json(); } catch { return ok(); }

  const msg    = body?.message;
  if (!msg) return ok();
  const chatId = String(msg.chat?.id);
  const text   = msg.text || '';

  if (chatId !== env.TELEGRAM_CHAT_ID) {
    await tgSend(env, chatId, '⛔ Không có quyền truy cập.');
    return ok();
  }

  const lower = text.trim().toLowerCase();
  if (lower.startsWith('/meeting '))  return handleMeetingCommand(env, chatId, text.slice(9).trim());
  if (lower === '/meetings')          return handleListMeetings(env, chatId);
  if (lower === '/tasks')             return handleListTasks(env, chatId);
  if (lower === '/help')              return handleHelp(env, chatId);
  if (lower.startsWith('/send_all ')) return handleSendAll(env, chatId, text.slice(10).trim());

  await tgSend(env, chatId, '❓ Lệnh không hợp lệ. Gõ /help để xem hướng dẫn.');
  return ok();
}

async function handleHelp(env, chatId) {
  const msg = `📖 <b>IDS Meeting Bot — Hướng dẫn</b>

<b>Tạo meeting (mời cả team):</b>
<code>/meeting "Tiêu đề" YYYY-MM-DD HH:MM phút IDS_Leaders</code>

<b>Tạo meeting (mời từng người):</b>
<code>/meeting "Tiêu đề" YYYY-MM-DD HH:MM phút email1 email2</code>

<b>Ví dụ:</b>
<code>/meeting "Review Q2 Castrol" 2026-05-10 14:00 60 IDS_Leaders</code>

<b>Xem meeting sắp tới:</b> <code>/meetings</code>
<b>Xem action items:</b> <code>/tasks</code>

💡 Pre-read: thêm <code>| tài liệu: https://...</code> vào cuối`;
  await tgSend(env, chatId, msg);
  return ok();
}

async function handleMeetingCommand(env, chatId, args) {
  await tgSend(env, chatId, '⏳ Đang tạo meeting...');
  try {
    let preRead = '';
    let mainPart = args;
    if (args.includes('| tài liệu:')) {
      const parts = args.split('| tài liệu:');
      mainPart = parts[0].trim();
      preRead  = parts[1].trim();
    }

    const titleMatch = mainPart.match(/^"([^"]+)"\s+(.+)$/);
    if (!titleMatch) {
      await tgSend(env, chatId, '❌ Sai format. Xem /help để biết cách dùng.');
      return ok();
    }

    const title    = titleMatch[1];
    const rest     = titleMatch[2].trim().split(/\s+/);
    if (rest.length < 4) {
      await tgSend(env, chatId, '❌ Thiếu thông tin. Cần: ngày giờ thời-lượng email...');
      return ok();
    }

    const dateStr  = rest[0];
    const timeStr  = rest[1];
    const duration = parseInt(rest[2]);
    let   emails   = rest.slice(3);

    if (emails.length === 1 && emails[0].toUpperCase() === 'IDS_LEADERS') {
      await tgSend(env, chatId, '📋 Đang lấy danh sách team...');
      emails = await getTeamEmails(env);
      if (!emails.length) {
        await tgSend(env, chatId, '❌ Không lấy được danh sách team. Kiểm tra Google Sheets tab Team và chạy Sync Team workflow.');
        return ok();
      }
      await tgSend(env, chatId, `👥 Mời ${emails.length} thành viên: ${emails.join(', ')}`);
    }

    const startTime  = `${dateStr}T${timeStr}:00`;
    const zoomToken  = await getZoomToken(env);
    const meeting    = await createZoomMeeting(env, zoomToken, title, startTime, duration, emails, preRead);

    await env.MEETINGS_KV.put(`meeting:${meeting.id}`, JSON.stringify({
      id: meeting.id, title, start_time: startTime, duration, emails, pre_read: preRead,
      created_at: new Date().toISOString()
    }), { expirationTtl: 60 * 60 * 24 * 30 });

    await scheduleReminder(env, meeting.id, title, startTime, chatId);

    // Gửi email invite qua GitHub Actions
    await triggerGitHubActions(env, 'send_invitations', {
      meeting_title: title,
      start_time   : startTime,
      duration_min : duration,
      join_url     : meeting.join_url,
      password     : meeting.password || '',
      meeting_id   : String(meeting.id),
      emails
    });

    const dt    = new Date(`${dateStr}T${timeStr}:00+07:00`);
    const dtStr = dt.toLocaleString('vi-VN', {
      timeZone: 'Asia/Ho_Chi_Minh', weekday: 'long',
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });

    await tgSend(env, chatId, `✅ <b>Meeting đã tạo!</b>

📌 <b>${title}</b>
📅 ${dtStr}
⏱ ${duration} phút · 👥 ${emails.length} người
${preRead ? `📎 Pre-read: ${preRead}` : ''}
🔗 <a href="${meeting.join_url}">Join Meeting</a>
🆔 Meeting ID: <code>${meeting.id}</code>
🔑 Passcode: <code>${meeting.password || 'Không có'}</code>

📨 Invite gửi đến: ${emails.join(', ')}`);

  } catch (err) {
    await tgSend(env, chatId, `❌ Lỗi tạo meeting: ${err.message}`);
  }
  return ok();
}

async function handleListMeetings(env, chatId) {
  try {
    const token = await getZoomToken(env);
    const r     = await fetch('https://api.zoom.us/v2/users/me/meetings?type=upcoming&page_size=5', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const meetings = (await r.json()).meetings || [];
    if (!meetings.length) {
      await tgSend(env, chatId, '📭 Không có meeting sắp tới.');
      return ok();
    }
    let msg = '📅 <b>Meeting sắp tới:</b>\n\n';
    for (const m of meetings) {
      const dt = new Date(m.start_time).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' });
      msg += `• <b>${m.topic}</b>\n  ${dt} · ${m.duration} phút\n  🔗 <a href="${m.join_url}">Join</a>\n\n`;
    }
    await tgSend(env, chatId, msg);
  } catch (err) {
    await tgSend(env, chatId, `❌ Lỗi: ${err.message}`);
  }
  return ok();
}

async function handleSendAll(env, chatId, meetingId) {
  if (!meetingId) {
    await tgSend(env, chatId, '❌ Thiếu meeting ID. Dùng: /send_all [meeting_id]');
    return ok();
  }
  await tgSend(env, chatId, `⏳ Đang gửi biên bản cho team (meeting ${meetingId})...`);
  try {
    await triggerGitHubActions(env, 'send_minutes_final', { meeting_id: meetingId });
    await tgSend(env, chatId, '✅ Đã kích hoạt gửi biên bản. Hoàn tất trong ~2 phút.');
  } catch (err) {
    await tgSend(env, chatId, `❌ Lỗi: ${err.message}`);
  }
  return ok();
}

async function handleListTasks(env, chatId) {
  await triggerGitHubActions(env, 'list_tasks', { chat_id: chatId });
  await tgSend(env, chatId, '⏳ Đang lấy danh sách tasks...');
  return ok();
}

// ─── ZOOM WEBHOOK ──────────────────────────────────────────────────────────

async function handleZoom(request, env) {
  const body = await request.text();
  let payload;
  try { payload = JSON.parse(body); } catch { return ok(); }

  // URL validation
  if (payload.event === 'endpoint.url_validation') {
    const { plainToken } = payload.payload;
    const hmac = await computeHmac(env.ZOOM_WEBHOOK_SECRET, plainToken);
    return new Response(JSON.stringify({ plainToken, encryptedToken: hmac }),
      { headers: { 'Content-Type': 'application/json' } });
  }

  // Verify signature
  const signature = request.headers.get('x-zm-signature') || '';
  const timestamp = request.headers.get('x-zm-request-timestamp') || '';
  const expected  = 'v0=' + await computeHmac(env.ZOOM_WEBHOOK_SECRET, `v0:${timestamp}:${body}`);
  if (signature !== expected) return new Response('Unauthorized', { status: 401 });

  if (payload.event === 'recording.completed') {
    const meetingId  = String(payload.payload?.object?.id || '');
    const meetingObj = payload.payload?.object || {};
    const stored     = await env.MEETINGS_KV.get(`meeting:${meetingId}`);
    const info       = stored ? JSON.parse(stored) : null;

    // Lấy audio URL trực tiếp từ webhook payload
    const recFiles = meetingObj.recording_files || [];
    const audioRec = recFiles.find(f => f.file_type === 'M4A')
                  || recFiles.find(f => f.file_type === 'MP4');

    // Participants = danh sách đã mời khi tạo meeting (lưu trong KV)
    const emails = info?.emails || [];

    await triggerGitHubActions(env, 'process_recording', {
      meeting_id   : meetingId,
      meeting_uuid : meetingObj.uuid || '',
      topic        : meetingObj.topic || info?.title || '',
      start_time   : meetingObj.start_time || info?.start_time || '',
      duration     : meetingObj.duration || info?.duration || 0,
      emails,
      host_email   : meetingObj.host_email || '',
      audio_url    : audioRec?.download_url || '',
      audio_type   : (audioRec?.file_type || '').toLowerCase()
    });
  }
  return ok();
}

// ─── HELPERS ───────────────────────────────────────────────────────────────

async function getZoomToken(env) {
  const creds = btoa(`${env.ZOOM_CLIENT_ID}:${env.ZOOM_CLIENT_SECRET}`);
  const r     = await fetch(
    `https://zoom.us/oauth/token?grant_type=account_credentials&account_id=${env.ZOOM_ACCOUNT_ID}`,
    { method: 'POST', headers: { 'Authorization': `Basic ${creds}` } }
  );
  const data = await r.json();
  if (!data.access_token) throw new Error(`Zoom auth failed: ${JSON.stringify(data)}`);
  return data.access_token;
}

async function createZoomMeeting(env, token, title, startTime, duration, emails, preRead) {
  const agendaNote = preRead ? `\n\n📎 Tài liệu đọc trước: ${preRead}` : '';
  const r = await fetch('https://api.zoom.us/v2/users/me/meetings', {
    method : 'POST',
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    body   : JSON.stringify({
      topic     : title, type: 2, start_time: startTime, duration,
      timezone  : 'Asia/Ho_Chi_Minh',
      agenda    : `Cuộc họp IDS${agendaNote}`,
      settings  : {
        auto_recording   : 'cloud', audio: 'both',
        join_before_host : true, waiting_room: false,
        meeting_invitees : emails.map(e => ({ email: e })),
        send_invitation  : true
      }
    })
  });
  const data = await r.json();
  if (!data.id) throw new Error(`Create meeting failed: ${JSON.stringify(data)}`);
  return data;
}

async function scheduleReminder(env, meetingId, title, startTime, chatId) {
  const remindAt = new Date(new Date(startTime + '+07:00').getTime() - 30 * 60 * 1000).toISOString();
  await env.MEETINGS_KV.put(`reminder:${meetingId}`, JSON.stringify({
    meeting_id: meetingId, title, remind_at: remindAt, chat_id: chatId, sent: false
  }), { expirationTtl: 60 * 60 * 24 * 7 });
}

async function getTeamEmails(env) {
  try {
    const cached = await env.MEETINGS_KV.get('team:emails');
    return cached ? JSON.parse(cached) : [];
  } catch { return []; }
}

async function triggerGitHubActions(env, eventType, payload) {
  const r = await fetch(
    'https://api.github.com/repos/NguyenPhinDeli/zoom-meeting-bot/dispatches',
    {
      method : 'POST',
      headers: {
        'Authorization': `Bearer ${env.GH_PAT}`,
        'Accept'       : 'application/vnd.github+json',
        'Content-Type' : 'application/json',
        'User-Agent'   : 'IDS-Meeting-Bot/1.0'
      },
      body: JSON.stringify({ event_type: eventType, client_payload: payload })
    }
  );
  if (!r.ok) throw new Error(`GH dispatch failed: ${await r.text()}`);
}

async function tgSend(env, chatId, text) {
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body   : JSON.stringify({
      chat_id: chatId, text, parse_mode: 'HTML', disable_web_page_preview: true
    })
  });
}

async function computeHmac(secret, message) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(message));
  return Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function ok() { return new Response('OK', { status: 200 }); }
