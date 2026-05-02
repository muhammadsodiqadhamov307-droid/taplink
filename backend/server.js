import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

import dotenv from "dotenv";
import express from "express";
import multer from "multer";
import { Server } from "socket.io";
import sqlite3 from "sqlite3";
import { open } from "sqlite";

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const frontendDir = path.join(projectRoot, "frontend");
const uploadsDir = path.join(__dirname, "uploads");

const PORT = Number(process.env.PORT || 3000);
const BOT_TOKEN = process.env.BOT_TOKEN;
const ADMIN_TELEGRAM_ID = String(process.env.ADMIN_TELEGRAM_ID || process.env.ADMIN_CHAT_ID || "");
const DATABASE_URL = process.env.DATABASE_URL || "sqlite://backend/chat.db";

if (!BOT_TOKEN) {
  throw new Error("BOT_TOKEN is required");
}

if (!ADMIN_TELEGRAM_ID) {
  throw new Error("ADMIN_TELEGRAM_ID or ADMIN_CHAT_ID is required");
}

fs.mkdirSync(uploadsDir, { recursive: true });

function sqlitePathFromUrl(databaseUrl) {
  if (!databaseUrl.startsWith("sqlite://")) {
    throw new Error("Only sqlite:// DATABASE_URL values are supported by this local server");
  }

  const dbPath = databaseUrl.replace("sqlite://", "");
  return path.isAbsolute(dbPath) ? dbPath : path.join(projectRoot, dbPath);
}

const db = await open({
  filename: sqlitePathFromUrl(DATABASE_URL),
  driver: sqlite3.Database,
});

await db.exec(`
  PRAGMA journal_mode = WAL;

  CREATE TABLE IF NOT EXISTS users (
    telegram_id TEXT PRIMARY KEY,
    first_name TEXT NOT NULL,
    age TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id TEXT NOT NULL,
    receiver_id TEXT NOT NULL,
    content TEXT,
    type TEXT NOT NULL CHECK(type IN ('text', 'image', 'video', 'file')),
    file_url TEXT,
    file_name TEXT,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_read INTEGER NOT NULL DEFAULT 0
  );

  CREATE INDEX IF NOT EXISTS idx_messages_pair_time
    ON messages(sender_id, receiver_id, timestamp);
`);

const upload = multer({
  storage: multer.diskStorage({
    destination: uploadsDir,
    filename: (req, file, cb) => {
      const safeName = file.originalname.replace(/[^a-zA-Z0-9._-]/g, "_");
      cb(null, `${Date.now()}-${crypto.randomUUID()}-${safeName}`);
    },
  }),
  limits: {
    fileSize: 50 * 1024 * 1024,
  },
});

function validateInitData(initData) {
  try {
    if (!initData) {
      return null;
    }

    const params = new URLSearchParams(initData);
    const hash = params.get("hash");
    params.delete("hash");

    if (!hash) {
      return null;
    }

    const dataCheckString = [...params.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) => `${key}=${value}`)
      .join("\n");

    const secretKey = crypto.createHmac("sha256", "WebAppData").update(BOT_TOKEN).digest();
    const calculatedHash = crypto
      .createHmac("sha256", secretKey)
      .update(dataCheckString)
      .digest("hex");

    const calculated = Buffer.from(calculatedHash);
    const received = Buffer.from(hash);

    if (calculated.length !== received.length || !crypto.timingSafeEqual(calculated, received)) {
      return null;
    }

    const userJson = params.get("user");
    if (!userJson) {
      return null;
    }

    const user = JSON.parse(userJson);
    return {
      telegramId: String(user.id),
      firstName: user.first_name || user.username || "User",
      username: user.username || "",
    };
  } catch {
    return null;
  }
}

function getRequestUser(req) {
  const initData = req.get("x-telegram-init-data") || req.body?.initData || req.query?.initData;
  const validated = validateInitData(initData);

  if (validated) {
    return {
      ...validated,
      isAdmin: validated.telegramId === ADMIN_TELEGRAM_ID,
    };
  }

  if (process.env.NODE_ENV !== "production" && process.env.DEV_TELEGRAM_ID) {
    const telegramId = String(process.env.DEV_TELEGRAM_ID);
    return {
      telegramId,
      firstName: process.env.DEV_FIRST_NAME || "Dev User",
      username: "dev",
      isAdmin: telegramId === ADMIN_TELEGRAM_ID,
    };
  }

  return null;
}

async function requireTelegramUser(req, res, next) {
  const user = getRequestUser(req);

  if (!user) {
    res.status(401).json({ error: "Invalid Telegram initData" });
    return;
  }

  req.telegramUser = user;
  next();
}

async function getUserById(telegramId) {
  return db.get(
    "SELECT telegram_id, first_name, age, created_at, updated_at FROM users WHERE telegram_id = ?",
    telegramId,
  );
}

async function getMessagesForUser(userId) {
  return db.all(
    `
      SELECT id, sender_id, receiver_id, content, type, file_url, file_name, timestamp, is_read
      FROM messages
      WHERE sender_id = ? OR receiver_id = ?
      ORDER BY datetime(timestamp) ASC, id ASC
    `,
    userId,
    userId,
  );
}

async function createMessage({ senderId, receiverId, content, type, fileUrl, fileName }) {
  const result = await db.run(
    `
      INSERT INTO messages (sender_id, receiver_id, content, type, file_url, file_name)
      VALUES (?, ?, ?, ?, ?, ?)
    `,
    senderId,
    receiverId,
    content || null,
    type,
    fileUrl || null,
    fileName || null,
  );

  return db.get(
    `
      SELECT id, sender_id, receiver_id, content, type, file_url, file_name, timestamp, is_read
      FROM messages
      WHERE id = ?
    `,
    result.lastID,
  );
}

async function getAdminUsers() {
  return db.all(`
    SELECT
      u.telegram_id,
      u.first_name,
      u.age,
      u.created_at,
      u.updated_at,
      COALESCE(last_message.content, last_message.file_name, '') AS last_message,
      last_message.type AS last_type,
      last_message.timestamp AS last_timestamp,
      COALESCE(unread.unread_count, 0) AS unread_count
    FROM users u
    LEFT JOIN (
      SELECT m.*
      FROM messages m
      INNER JOIN (
        SELECT
          CASE
            WHEN sender_id = ? THEN receiver_id
            ELSE sender_id
          END AS user_id,
          MAX(id) AS max_id
        FROM messages
        WHERE sender_id = ? OR receiver_id = ?
        GROUP BY user_id
      ) grouped ON grouped.max_id = m.id
    ) last_message
      ON last_message.sender_id = u.telegram_id OR last_message.receiver_id = u.telegram_id
    LEFT JOIN (
      SELECT sender_id AS user_id, COUNT(*) AS unread_count
      FROM messages
      WHERE receiver_id = ? AND is_read = 0
      GROUP BY sender_id
    ) unread ON unread.user_id = u.telegram_id
    ORDER BY
      CASE WHEN last_message.timestamp IS NULL THEN 1 ELSE 0 END,
      datetime(last_message.timestamp) DESC,
      datetime(u.updated_at) DESC
  `, ADMIN_TELEGRAM_ID, ADMIN_TELEGRAM_ID, ADMIN_TELEGRAM_ID, ADMIN_TELEGRAM_ID);
}

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: { origin: true },
  maxHttpBufferSize: 50 * 1024 * 1024,
});

app.use(express.json());
app.use("/uploads", express.static(uploadsDir));
app.use(express.static(frontendDir));

app.post("/api/auth", requireTelegramUser, async (req, res) => {
  const profile = await getUserById(req.telegramUser.telegramId);
  res.json({
    telegramId: req.telegramUser.telegramId,
    firstName: profile?.first_name || req.telegramUser.firstName,
    age: profile?.age || "",
    isAdmin: req.telegramUser.isAdmin,
  });
});

app.get("/api/me/messages", requireTelegramUser, async (req, res) => {
  if (req.telegramUser.isAdmin) {
    res.status(400).json({ error: "Admin must request a specific user chat" });
    return;
  }

  res.json(await getMessagesForUser(req.telegramUser.telegramId));
});

app.get("/api/admin/users", requireTelegramUser, async (req, res) => {
  if (!req.telegramUser.isAdmin) {
    res.status(403).json({ error: "Admin only" });
    return;
  }

  res.json(await getAdminUsers());
});

app.get("/api/admin/users/:telegramId/messages", requireTelegramUser, async (req, res) => {
  if (!req.telegramUser.isAdmin) {
    res.status(403).json({ error: "Admin only" });
    return;
  }

  await db.run(
    "UPDATE messages SET is_read = 1 WHERE sender_id = ? AND receiver_id = ?",
    req.params.telegramId,
    ADMIN_TELEGRAM_ID,
  );

  res.json(await getMessagesForUser(req.params.telegramId));
});

app.post("/api/uploads", requireTelegramUser, upload.single("file"), async (req, res) => {
  if (!req.file) {
    res.status(400).json({ error: "No file uploaded" });
    return;
  }

  const mime = req.file.mimetype || "";
  const type = mime.startsWith("image/")
    ? "image"
    : mime.startsWith("video/")
      ? "video"
      : "file";

  res.json({
    type,
    fileUrl: `/uploads/${req.file.filename}`,
    fileName: req.file.originalname,
  });
});

io.use((socket, next) => {
  const user = validateInitData(socket.handshake.auth?.initData);

  if (!user && !(process.env.NODE_ENV !== "production" && process.env.DEV_TELEGRAM_ID)) {
    next(new Error("Invalid Telegram initData"));
    return;
  }

  const telegramUser = user || {
    telegramId: String(process.env.DEV_TELEGRAM_ID),
    firstName: process.env.DEV_FIRST_NAME || "Dev User",
    username: "dev",
  };

  socket.telegramUser = {
    ...telegramUser,
    isAdmin: telegramUser.telegramId === ADMIN_TELEGRAM_ID,
  };
  next();
});

io.on("connection", async (socket) => {
  const user = socket.telegramUser;
  socket.join(`user:${user.telegramId}`);

  if (user.isAdmin) {
    socket.join("admin");
    socket.emit("admin:users", await getAdminUsers());
  }

  socket.on("message:send", async (payload, ack) => {
    try {
      const isAdmin = user.isAdmin;
      const receiverId = isAdmin ? String(payload.receiverId || "") : ADMIN_TELEGRAM_ID;

      if (!receiverId) {
        throw new Error("receiverId is required");
      }

      const message = await createMessage({
        senderId: user.telegramId,
        receiverId,
        content: payload.content,
        type: payload.type || "text",
        fileUrl: payload.fileUrl,
        fileName: payload.fileName,
      });

      io.to(`user:${message.sender_id}`).emit("message:new", message);
      io.to(`user:${message.receiver_id}`).emit("message:new", message);
      io.to("admin").emit("admin:users", await getAdminUsers());
      ack?.({ ok: true, message });
    } catch (error) {
      ack?.({ ok: false, error: error.message });
    }
  });

  socket.on("messages:read", async ({ userId } = {}) => {
    if (!user.isAdmin || !userId) {
      return;
    }

    await db.run(
      "UPDATE messages SET is_read = 1 WHERE sender_id = ? AND receiver_id = ?",
      String(userId),
      ADMIN_TELEGRAM_ID,
    );
    io.to("admin").emit("admin:users", await getAdminUsers());
  });
});

server.listen(PORT, () => {
  console.log(`Mini App server listening on http://localhost:${PORT}`);
});
