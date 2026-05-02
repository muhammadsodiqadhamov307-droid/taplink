import { FormEvent, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { io, Socket } from "socket.io-client";
import {
  ArrowLeft,
  CheckCheck,
  FileText,
  Mic,
  Plus,
  Search,
  Send,
  StopCircle,
  X,
} from "lucide-react";

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData?: string;
        ready: () => void;
        expand: () => void;
      };
    };
  }
}

type MessageType = "text" | "image" | "video" | "audio" | "file";

interface CurrentUser {
  telegramId: string;
  firstName: string;
  age: string;
  isAdmin: boolean;
}

interface ChatUser {
  telegram_id: string;
  first_name: string;
  age: string;
  last_message: string;
  last_type: MessageType | null;
  last_timestamp: string | null;
  unread_count: number;
}

interface Message {
  id: number;
  sender_id: string;
  receiver_id: string;
  content: string | null;
  type: MessageType;
  file_url: string | null;
  file_name: string | null;
  timestamp: string;
  is_read: number;
}

const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const initData = tg?.initData || "";
const authHeaders = initData ? { "x-telegram-init-data": initData } : {};

function formatTime(value?: string | null) {
  if (!value) {
    return "";
  }

  const normalized = /[zZ]|[+-]\d\d:?\d\d$/.test(value)
    ? value
    : `${value.replace(" ", "T")}Z`;

  return new Date(normalized).toLocaleTimeString("uz-UZ", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Tashkent",
  });
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "?";
}

function previewFor(user: ChatUser) {
  if (user.last_message) {
    return user.last_message;
  }

  if (user.last_type === "image") return "Rasm";
  if (user.last_type === "video") return "Video";
  if (user.last_type === "audio") return "Ovozli xabar";
  if (user.last_type === "file") return "Fayl";
  return "Bot orqali kelgan xabarlar";
}

function uniqueUsers(users: ChatUser[]) {
  const seen = new Set<string>();
  return users.filter((user) => {
    if (seen.has(user.telegram_id)) {
      return false;
    }

    seen.add(user.telegram_id);
    return true;
  });
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...authHeaders,
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

function Avatar({ user }: { user: ChatUser }) {
  return (
    <div className="avatar">
      {initials(user.first_name)}
    </div>
  );
}

function RecordingWave() {
  return (
    <div className="recording-wave" aria-label="Ovoz yozilmoqda">
      <span>Ovoz yozilmoqda</span>
      <div className="wave-bars">
        {Array.from({ length: 24 }).map((_, index) => (
          <i key={index} style={{ animationDelay: `${index * 0.055}s` }} />
        ))}
      </div>
    </div>
  );
}

function MessageBody({ message, onOpenImage }: { message: Message; onOpenImage: (src: string) => void }) {
  if (message.type === "image" && message.file_url) {
    return (
      <button className="image-preview-button" type="button" onClick={() => onOpenImage(message.file_url!)}>
        <img className="media-preview" src={message.file_url} alt={message.file_name || "Rasm"} />
      </button>
    );
  }

  if (message.type === "video" && message.file_url) {
    return <video className="media-preview" src={message.file_url} controls />;
  }

  if (message.type === "audio" && message.file_url) {
    return <audio className="audio-preview" src={message.file_url} controls />;
  }

  if (message.type === "file" && message.file_url) {
    return (
      <a className="file-chip" href={message.file_url} target="_blank" rel="noreferrer">
        <FileText className="h-5 w-5" />
        <span>{message.file_name || "Fayl"}</span>
      </a>
    );
  }

  return <p className="message-text">{message.content}</p>;
}

export default function App() {
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [users, setUsers] = useState<ChatUser[]>([]);
  const [selectedUser, setSelectedUser] = useState<ChatUser | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [screen, setScreen] = useState<"list" | "chat">("list");
  const [error, setError] = useState("");
  const [isRecordingAudio, setIsRecordingAudio] = useState(false);
  const [fullScreenImage, setFullScreenImage] = useState<string | null>(null);
  const socketRef = useRef<Socket | null>(null);
  const selectedUserRef = useRef<ChatUser | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  useEffect(() => {
    selectedUserRef.current = selectedUser;
  }, [selectedUser]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, screen]);

  useEffect(() => {
    boot();

    return () => {
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.stop();
      }
      streamRef.current?.getTracks().forEach((track) => track.stop());
      socketRef.current?.disconnect();
    };
  }, []);

  async function boot() {
    try {
      const currentUser = await api<CurrentUser>("/api/auth", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ initData }),
      });

      setMe(currentUser);

      if (!currentUser.isAdmin) {
        setError("Bu Mini App faqat shifokor/admin uchun.");
        return;
      }

      await refreshUsers();
      connectSocket();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Mini App ochilmadi");
    }
  }

  function connectSocket() {
    const socket = io({ auth: { initData } });
    socketRef.current = socket;

    socket.on("message:new", (message: Message) => {
      const activeUser = selectedUserRef.current;
      setMessages((current) => {
        if (
          activeUser &&
          (message.sender_id === activeUser.telegram_id || message.receiver_id === activeUser.telegram_id)
        ) {
          return current.some((item) => item.id === message.id) ? current : [...current, message];
        }

        return current;
      });
      refreshUsers();
    });

    socket.on("admin:users", (updatedUsers: ChatUser[]) => {
      const dedupedUsers = uniqueUsers(updatedUsers);
      setUsers(dedupedUsers);
      setSelectedUser((current) => {
        if (!current) return current;
        return dedupedUsers.find((user) => user.telegram_id === current.telegram_id) || current;
      });
    });
  }

  async function refreshUsers() {
    const nextUsers = uniqueUsers(await api<ChatUser[]>("/api/admin/users"));
    setUsers(nextUsers);
    return nextUsers;
  }

  async function openChat(user: ChatUser) {
    setSelectedUser(user);
    setScreen("chat");
    const thread = await api<Message[]>(`/api/admin/users/${user.telegram_id}/messages`);
    setMessages(thread);
    socketRef.current?.emit("messages:read", { userId: user.telegram_id });
    refreshUsers();
  }

  function sendSocketMessage(payload: Partial<Message>) {
    if (!selectedUser) {
      return;
    }

    socketRef.current?.emit(
      "message:send",
      {
        ...payload,
        receiverId: selectedUser.telegram_id,
      },
      (result) => {
        if (!result?.ok) {
          alert(result?.error || "Xabar yuborilmadi");
        }
      },
    );
  }

  function sendTextMessage(event: FormEvent) {
    event.preventDefault();
    const content = inputValue.trim();

    if (!content) {
      return;
    }

    setInputValue("");
    sendSocketMessage({ type: "text", content });
  }

  async function sendFileMessage(file: File) {
    if (!selectedUser) {
      return;
    }

    const form = new FormData();
    form.append("file", file);
    const uploaded = await api<Partial<Message>>("/api/uploads", {
      method: "POST",
      headers: authHeaders,
      body: form,
    });
    sendSocketMessage(uploaded);
  }

  function recordingMimeType() {
    const options = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];

    return options.find((mimeType) => MediaRecorder.isTypeSupported(mimeType)) || "";
  }

  async function startAudioRecording() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      alert("Brauzer ovoz yozishni qo'llab-quvvatlamaydi.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = recordingMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      streamRef.current = stream;
      recorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        const file = new File([blob], `doctor-audio-${Date.now()}.webm`, { type: blob.type });
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        recorderRef.current = null;
        chunksRef.current = [];
        setIsRecordingAudio(false);

        if (blob.size > 0) {
          await sendFileMessage(file);
        }
      };

      recorder.start();
      setIsRecordingAudio(true);
    } catch (err) {
      setIsRecordingAudio(false);
      alert(err instanceof Error ? err.message : "Ovoz yozib bo'lmadi.");
    }
  }

  function stopRecording() {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    }
  }

  function handleMediaButton() {
    if (isRecordingAudio) {
      stopRecording();
      return;
    }

    startAudioRecording();
  }

  if (error) {
    return (
      <div className="center-state">
        <p>{error}</p>
      </div>
    );
  }

  if (!me) {
    return (
      <div className="center-state">
        <div className="loader" />
        <p>Chatlar yuklanmoqda...</p>
      </div>
    );
  }

  return (
    <div className="mini-shell">
      <AnimatePresence mode="wait">
        {screen === "list" ? (
          <motion.section
            key="list"
            initial={{ x: -20, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: -20, opacity: 0 }}
            className="list-screen"
          >
            <header className="app-header">
              <h1>Chatlar</h1>
              <div className="header-actions">
                <Search className="h-5 w-5" />
                <span className="count-pill">{users.length}</span>
              </div>
            </header>

            <main className="user-list">
              {users.map((user) => (
                <button
                  key={user.telegram_id}
                  type="button"
                  className="user-row"
                  onClick={() => openChat(user)}
                >
                  <Avatar user={user} />
                  <div className="user-main">
                    <div className="user-line">
                      <strong>{user.first_name}, {user.age}</strong>
                      <span>{formatTime(user.last_timestamp)}</span>
                    </div>
                    <div className="user-line muted">
                      <span>{previewFor(user)}</span>
                      {user.unread_count > 0 && <b className="badge">{user.unread_count}</b>}
                    </div>
                  </div>
                </button>
              ))}

              {!users.length && (
                <div className="empty-list">Hali xabar kelmagan</div>
              )}
            </main>
          </motion.section>
        ) : (
          <motion.section
            key="chat"
            initial={{ x: 20, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 20, opacity: 0 }}
            className="chat-screen"
          >
            <header className="chat-header">
              <button className="icon-button" type="button" onClick={() => setScreen("list")}>
                <ArrowLeft className="h-6 w-6" />
              </button>
              {selectedUser && (
                <>
                  <Avatar user={selectedUser} />
                  <div className="chat-title">
                    <strong>{selectedUser.first_name}</strong>
                    <span>{selectedUser.age} yosh</span>
                  </div>
                </>
              )}
            </header>

            <main className="messages">
              <div className="day-chip">Bugun</div>
              {messages.map((message) => {
                const outgoing = message.sender_id === me.telegramId;
                return (
                  <article key={message.id} className={`message ${outgoing ? "outgoing" : "incoming"}`}>
                    <MessageBody message={message} onOpenImage={setFullScreenImage} />
                    <div className="message-meta">
                      <span>{formatTime(message.timestamp)}</span>
                      {outgoing && <CheckCheck className="h-3.5 w-3.5" />}
                    </div>
                  </article>
                );
              })}
              <div ref={chatEndRef} />
            </main>

            <form className="composer" onSubmit={sendTextMessage}>
              <input
                ref={fileInputRef}
                type="file"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) sendFileMessage(file);
                }}
              />
              <button className="attach-button" type="button" onClick={() => fileInputRef.current?.click()}>
                <Plus className="h-6 w-6" />
              </button>
              {isRecordingAudio ? (
                <RecordingWave />
              ) : (
                <input
                  value={inputValue}
                  onChange={(event) => setInputValue(event.target.value)}
                  placeholder="Xabar yozing..."
                />
              )}
              <button
                className={`send-button ${isRecordingAudio ? "recording" : ""}`}
                type={inputValue.trim() && !isRecordingAudio ? "submit" : "button"}
                onClick={inputValue.trim() || isRecordingAudio ? (isRecordingAudio ? stopRecording : undefined) : handleMediaButton}
                title={isRecordingAudio ? "Yuborish" : "Ovoz yozish"}
              >
                {isRecordingAudio ? (
                  <StopCircle className="h-6 w-6" />
                ) : inputValue.trim() ? (
                  <Send className="h-5 w-5" />
                ) : (
                  <Mic className="h-6 w-6" />
                )}
              </button>
            </form>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {fullScreenImage && (
          <motion.div
            className="image-lightbox"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setFullScreenImage(null)}
          >
            <button className="lightbox-close" type="button" aria-label="Yopish" onClick={() => setFullScreenImage(null)}>
              <X className="h-6 w-6" />
            </button>
            <img src={fullScreenImage} alt="Rasm" onClick={(event) => event.stopPropagation()} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
