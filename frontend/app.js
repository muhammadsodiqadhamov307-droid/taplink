const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const initData = tg?.initData || "";
const apiHeaders = initData ? { "x-telegram-init-data": initData } : {};

const state = {
  me: null,
  socket: null,
  selectedUserId: null,
  messages: [],
};

const app = document.getElementById("app");

function formatTime(value) {
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...apiHeaders,
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

function renderShell() {
  app.innerHTML = "";
  app.append(document.getElementById("chat-template").content.cloneNode(true));

  document.getElementById("messageForm").addEventListener("submit", sendTextMessage);
  document.getElementById("attachButton").addEventListener("click", () => {
    document.getElementById("fileInput").click();
  });
  document.getElementById("fileInput").addEventListener("change", sendFileMessage);

  if (state.me.isAdmin) {
    document.getElementById("userListPanel").classList.remove("hidden");
    document.getElementById("chatTitle").textContent = "Foydalanuvchini tanlang";
    document.getElementById("chatSubtitle").textContent = "Chap tomondan chatni oching";
    document.getElementById("messages").innerHTML = "<div class=\"empty-state\">Chat tanlanmagan</div>";
  } else {
    document.getElementById("chatTitle").textContent = "Dr. Farangisxon Yusufjonova";
    document.getElementById("chatSubtitle").textContent = "Online maslahat";
    loadMyMessages();
  }
}

function renderMessages(messages) {
  const box = document.getElementById("messages");
  box.innerHTML = "";

  if (!messages.length) {
    box.innerHTML = "<div class=\"empty-state\">Hali xabar yo'q</div>";
    return;
  }

  for (const message of messages) {
    const mine = message.sender_id === state.me.telegramId;
    const bubble = document.createElement("article");
    bubble.className = `message ${mine ? "mine" : "theirs"}`;

    if (message.type === "image") {
      bubble.innerHTML = `<img src="${message.file_url}" alt="${message.file_name || "image"}">`;
    } else if (message.type === "video") {
      bubble.innerHTML = `<video src="${message.file_url}" controls></video>`;
    } else if (message.type === "file") {
      bubble.innerHTML = `<a class="file-link" href="${message.file_url}" target="_blank" rel="noopener">${message.file_name || "Fayl"}</a>`;
    } else {
      bubble.innerHTML = `<div class="message-text"></div>`;
      bubble.querySelector(".message-text").textContent = message.content || "";
    }

    const time = document.createElement("div");
    time.className = "message-time";
    time.textContent = formatTime(message.timestamp);
    bubble.append(time);
    box.append(bubble);
  }

  box.scrollTop = box.scrollHeight;
}

async function loadMyMessages() {
  state.messages = await api("/api/me/messages");
  renderMessages(state.messages);
}

async function loadAdminUsers(users) {
  const list = document.getElementById("userList");
  const items = users || await api("/api/admin/users");
  document.getElementById("chatCount").textContent = items.length;
  list.innerHTML = "";

  for (const user of items) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `user-row ${state.selectedUserId === user.telegram_id ? "active" : ""}`;
    row.innerHTML = `
      <div class="user-topline">
        <span>${user.first_name}, ${user.age}</span>
        ${user.unread_count ? `<span class="badge">${user.unread_count}</span>` : ""}
      </div>
      <div class="user-preview">${user.last_message || "Hali xabar yo'q"}</div>
    `;
    row.addEventListener("click", () => selectAdminUser(user));
    list.append(row);
  }
}

async function selectAdminUser(user) {
  state.selectedUserId = user.telegram_id;
  document.getElementById("chatTitle").textContent = `${user.first_name}, ${user.age}`;
  document.getElementById("chatSubtitle").textContent = `Telegram ID: ${user.telegram_id}`;
  state.messages = await api(`/api/admin/users/${user.telegram_id}/messages`);
  renderMessages(state.messages);
  state.socket.emit("messages:read", { userId: user.telegram_id });
  loadAdminUsers();
}

async function sendTextMessage(event) {
  event.preventDefault();
  const input = document.getElementById("messageInput");
  const content = input.value.trim();

  if (!content) {
    return;
  }

  input.value = "";
  sendSocketMessage({ type: "text", content });
}

async function sendFileMessage(event) {
  const file = event.target.files?.[0];
  event.target.value = "";

  if (!file) {
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  const uploaded = await api("/api/uploads", {
    method: "POST",
    body: formData,
    headers: apiHeaders,
  });

  sendSocketMessage(uploaded);
}

function sendSocketMessage(payload) {
  if (state.me.isAdmin && !state.selectedUserId) {
    alert("Avval foydalanuvchini tanlang");
    return;
  }

  state.socket.emit(
    "message:send",
    {
      ...payload,
      receiverId: state.me.isAdmin ? state.selectedUserId : undefined,
    },
    (result) => {
      if (!result?.ok) {
        alert(result?.error || "Xabar yuborilmadi");
      }
    },
  );
}

function connectSocket() {
  state.socket = io({
    auth: { initData },
  });

  state.socket.on("message:new", (message) => {
    const belongsToOpenAdminChat =
      state.me.isAdmin &&
      state.selectedUserId &&
      (message.sender_id === state.selectedUserId || message.receiver_id === state.selectedUserId);

    if (!state.me.isAdmin || belongsToOpenAdminChat) {
      state.messages.push(message);
      renderMessages(state.messages);
    }

    if (state.me.isAdmin) {
      loadAdminUsers();
    }
  });

  state.socket.on("admin:users", (users) => {
    if (state.me.isAdmin) {
      loadAdminUsers(users);
    }
  });
}

async function boot() {
  try {
    state.me = await api("/api/auth", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ initData }),
    });
    renderShell();
    connectSocket();

    if (state.me.isAdmin) {
      loadAdminUsers();
    }
  } catch (error) {
    app.innerHTML = `<section class="loading-view"><p>Mini App ochilmadi.</p><small>${error.message}</small></section>`;
  }
}

boot();
