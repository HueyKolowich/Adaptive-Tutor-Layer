const express = require('express');
const path = require('path');
const { createClient } = require('redis');

const app = express();

const PORT = parseInt(process.env.PORT || '3001', 10);
const REDIS_URL = process.env.OBS_REDIS_URL || process.env.REDIS_URL || 'redis://redis:6379/0';
const STREAM_KEY = process.env.OBS_REDIS_STREAM_KEY || 'atl:state-events';
const REPLAY_LIMIT = parseInt(process.env.PANEL_REPLAY_LIMIT || '100', 10);

app.use(express.static(path.join(__dirname, 'public')));

function toFieldMap(rawFields) {
  const fields = {};
  for (let i = 0; i < rawFields.length; i += 2) {
    fields[rawFields[i]] = rawFields[i + 1];
  }
  return fields;
}

function parseEventFromEntry(entry) {
  if (!Array.isArray(entry) || entry.length < 2) {
    return null;
  }
  const fields = toFieldMap(entry[1]);
  if (!fields.event) {
    return null;
  }
  try {
    return {
      redisId: entry[0],
      event: JSON.parse(fields.event),
    };
  } catch (err) {
    return null;
  }
}

function previousStreamId(id) {
  const parts = id.split('-');
  if (parts.length !== 2) {
    return '0-0';
  }
  const ms = Number(parts[0]);
  const seq = Number(parts[1]);
  if (Number.isNaN(ms) || Number.isNaN(seq)) {
    return '0-0';
  }
  if (seq > 0) {
    return `${ms}-${seq - 1}`;
  }
  if (ms <= 0) {
    return '0-0';
  }
  return `${ms - 1}-18446744073709551615`;
}

function matchesFilter(event, conversationId, userId) {
  if (!event) {
    return false;
  }
  if (userId) {
    return event.user_id === userId;
  }
  if (conversationId) {
    return event.conversation_id === conversationId;
  }
  return false;
}

async function fetchReplayEvents(client, conversationId, userId, limit) {
  const out = [];
  let end = '+';

  while (out.length < limit) {
    const rows = await client.sendCommand([
      'XREVRANGE',
      STREAM_KEY,
      end,
      '-',
      'COUNT',
      '250',
    ]);
    if (!Array.isArray(rows) || rows.length === 0) {
      break;
    }

    for (const row of rows) {
      const parsed = parseEventFromEntry(row);
      if (!parsed || !parsed.event) {
        continue;
      }
      if (matchesFilter(parsed.event, conversationId, userId)) {
        out.push(parsed);
        if (out.length >= limit) {
          break;
        }
      }
    }

    const oldest = rows[rows.length - 1];
    if (!oldest || !oldest[0] || oldest[0] === '0-0') {
      break;
    }
    end = previousStreamId(oldest[0]);
  }

  out.reverse();
  return out;
}

function writeSseEvent(res, eventName, payload) {
  res.write(`event: ${eventName}\n`);
  res.write(`data: ${JSON.stringify(payload)}\n\n`);
}

app.get('/health', (req, res) => {
  res.json({ ok: true, stream_key: STREAM_KEY });
});

app.get('/events', async (req, res) => {
  const conversationId = `${req.query.conversation_id || ''}`.trim();
  const userId = `${req.query.user_id || ''}`.trim();
  if (!conversationId && !userId) {
    return res.status(400).json({ detail: 'conversation_id or user_id query param is required.' });
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache, no-transform');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders?.();

  const commandClient = createClient({ url: REDIS_URL });
  const streamClient = commandClient.duplicate();
  let closed = false;

  const close = async () => {
    if (closed) {
      return;
    }
    closed = true;
    clearInterval(keepAlive);
    try {
      await streamClient.quit();
    } catch (_) {}
    try {
      await commandClient.quit();
    } catch (_) {}
  };

  req.on('close', close);
  req.on('aborted', close);

  const keepAlive = setInterval(() => {
    if (!closed) {
      res.write(': keepalive\n\n');
    }
  }, 15000);

  try {
    await commandClient.connect();
    await streamClient.connect();

    const replay = await fetchReplayEvents(commandClient, conversationId, userId, REPLAY_LIMIT);
    for (const item of replay) {
      writeSseEvent(res, 'state', item.event);
    }

    writeSseEvent(res, 'ready', {
      conversation_id: conversationId,
      user_id: userId || null,
      mode: userId ? 'user' : 'conversation',
      replay_count: replay.length,
      stream_key: STREAM_KEY,
    });

    let lastId = '$';
    const latest = await commandClient.sendCommand(['XREVRANGE', STREAM_KEY, '+', '-', 'COUNT', '1']);
    if (Array.isArray(latest) && latest.length > 0 && latest[0][0]) {
      lastId = latest[0][0];
    }

    while (!closed) {
      let rows;
      try {
        rows = await streamClient.sendCommand([
          'XREAD',
          'BLOCK',
          '15000',
          'COUNT',
          '100',
          'STREAMS',
          STREAM_KEY,
          lastId,
        ]);
      } catch (err) {
        if (!closed) {
          writeSseEvent(res, 'error', {
            detail: `Redis read failed: ${err.message}`,
          });
        }
        continue;
      }

      if (!Array.isArray(rows)) {
        continue;
      }

      for (const stream of rows) {
        const entries = stream[1] || [];
        for (const entry of entries) {
          if (!Array.isArray(entry) || !entry[0]) {
            continue;
          }
          lastId = entry[0];
          const parsed = parseEventFromEntry(entry);
          if (!parsed || !parsed.event) {
            continue;
          }
          if (!matchesFilter(parsed.event, conversationId, userId)) {
            continue;
          }
          writeSseEvent(res, 'state', parsed.event);
        }
      }
    }
  } catch (err) {
    writeSseEvent(res, 'error', {
      detail: `SSE setup failed: ${err.message}`,
    });
    await close();
  }
});

app.listen(PORT, () => {
  // eslint-disable-next-line no-console
  console.log(`panel-service listening on http://0.0.0.0:${PORT}`);
});
