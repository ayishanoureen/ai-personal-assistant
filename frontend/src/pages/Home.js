import React, { useEffect, useState, useRef, useCallback } from "react";
import "../App.css";
import API from "../api/axios";

export default function Home() {
    const [message, setMessage] = useState("");
    const userName = sessionStorage.getItem("userName");
    const firstName = userName?.split(" ")[0] || "";
    const [chat, setChat] = useState([
        { sender: "ai", text: userName ? `Hello ${firstName}! I am your AI Personal Assistant. How can I help you today?` : "Hello! I am your AI Personal Assistant. How can I help you today?" }
    ]);
    const [isLoading, setIsLoading] = useState(false);
    const [isListening, setIsListening] = useState(false)
    const [isMuted, setIsMuted] = useState(false);
    const [selectedImage, setSelectedImage] = useState(null);
    const chatEndRef = useRef(null);
    const fileInputRef = useRef(null);
    const sendToBackendRef = useRef(null);
    const transcriptRef = useRef("");



    const [reminders, setReminders] = useState([]);
    const [notes, setNotes] = useState([]);
    const [dashboardLoading, setDashboardLoading] = useState(false);
    const [editingReminder, setEditingReminder] = useState(null);
    const [editReminderText, setEditReminderText] = useState("");
    const [editReminderTime, setEditReminderTime] = useState("");
    const [editReminderRepeat, setEditReminderRepeat] = useState("none");
    const [editingNote, setEditingNote] = useState(null);
    const [editNoteContent, setEditNoteContent] = useState("");
    const [dashboardMsg, setDashboardMsg] = useState("");

    const scrollToBottom = () => {
        chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [chat, isLoading]);

    const fetchReminders = useCallback(async () => {
        try {
            const res = await API.get(`/reminders?t=${Date.now()}`);
            setReminders(res.data.reminders || []);
        } catch (err) {
            console.error("Error fetching reminders:", err);
        }
    }, []);

    const fetchNotes = useCallback(async () => {
        try {
            const res = await API.get(`/notes?t=${Date.now()}`);
            setNotes(res.data.notes || []);
        } catch (err) {
            console.error("Error fetching notes:", err);
        }
    }, []);

    const fetchDashboard = useCallback(async () => {
        try {
            setDashboardLoading(true);

            await Promise.all([
                fetchReminders(),
                fetchNotes()
            ]);

        } catch (err) {
            console.error("Dashboard fetch error:", err);
        } finally {
            setDashboardLoading(false);
        }
    }, [fetchReminders, fetchNotes]);

    useEffect(() => {
        fetchDashboard();
    }, [fetchDashboard]);

    const handleLogout = () => {
        sessionStorage.removeItem("token");
        sessionStorage.removeItem("userName");
        localStorage.removeItem("lastActivity");
        window.location.href = "/login";
    };

    const showDashboardMsg = (msg) => {
        setDashboardMsg(msg);
        setTimeout(() => setDashboardMsg(""), 3000);
    };

    const handleDeleteReminder = async (id) => {
        if (!window.confirm("Are you sure you want to delete this reminder?")) return;
        try {
            await API.delete(`/reminders/${id}`);
            setReminders(prev => prev.filter(r => r.id !== id));
            showDashboardMsg("Reminder deleted successfully");
        } catch (err) {
            showDashboardMsg("Failed to delete reminder");
        }
    };

    const handleDeleteNote = async (id) => {
        if (!window.confirm("Are you sure you want to delete this note?")) return;
        try {
            await API.delete(`/notes/${id}`);
            setNotes(prev => prev.filter(n => n.id !== id));
            showDashboardMsg("Note deleted successfully");
        } catch (err) {
            showDashboardMsg("Failed to delete note");
        }
    };

    const startEditReminder = (reminder) => {
        setEditingReminder(reminder.id);
        setEditReminderText(reminder.text);
        setEditReminderTime(reminder.time);
        setEditReminderRepeat(reminder.repeat_type || "none");;
    };

    const cancelEditReminder = () => {
        setEditingReminder(null);
        setEditReminderText("");
        setEditReminderTime("");
        setEditReminderRepeat("none");
    };

    const saveEditReminder = async (id) => {
        if (!editReminderText.trim()) {
            showDashboardMsg("Reminder text cannot be empty");
            return;
        }
        try {
            await API.put(`/reminders/${id}`, {
                text: editReminderText.trim(),
                time: editReminderTime.trim(),
                repeat_type: editReminderRepeat
            });
            setReminders(prev => prev.map(r =>
                r.id === id ? { ...r, text: editReminderText.trim(), time: editReminderTime.trim(), repeat_type: editReminderRepeat } : r
            ));
            cancelEditReminder();
            showDashboardMsg("Reminder updated successfully");
        } catch (err) {
            showDashboardMsg("Failed to update reminder");
        }
    };

    const startEditNote = (note) => {
        setEditingNote(note.id);
        setEditNoteContent(note.content);
    };

    const cancelEditNote = () => {
        setEditingNote(null);
        setEditNoteContent("");
    };

    const saveEditNote = async (id) => {
        if (!editNoteContent.trim()) {
            showDashboardMsg("Note content cannot be empty");
            return;
        }
        try {
            await API.put(`/notes/${id}`, {
                content: editNoteContent.trim()
            });
            setNotes(prev => prev.map(n =>
                n.id === id ? { ...n, content: editNoteContent.trim() } : n
            ));
            cancelEditNote();
            showDashboardMsg("Note updated successfully");
        } catch (err) {
            showDashboardMsg("Failed to update note");
        }
    };

    const speakText = (text) => {
        if (isMuted) return;
        window.speechSynthesis.cancel();

        let textToSpeak = "";
        if (typeof text === "string") {
            textToSpeak = text;
        } else if (text && typeof text === "object") {
            textToSpeak = text.summary || text.text || "";
        }

        if (!textToSpeak.trim()) return;

        const utterance = new SpeechSynthesisUtterance(textToSpeak);
        utterance.lang = "en-US";
        utterance.rate = 1;
        utterance.pitch = 1;
        utterance.volume = 1;
        window.speechSynthesis.speak(utterance);
    };

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognitionRef = useRef(null);
    const voiceTimeoutRef = useRef(null);
    const isSendingRef = useRef(false);
    const voiceCooldownRef = useRef(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => {
        if (!SpeechRecognition) return;

        const recognition = new SpeechRecognition();

        recognition.continuous = true;
        recognition.lang = "en-US";
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;

        recognition.onstart = () => {
            setIsListening(true);
        };

        recognition.onend = () => {
            setIsListening(false);

            if (voiceTimeoutRef.current) {
                clearTimeout(voiceTimeoutRef.current);
            }

            const finalSpeech = transcriptRef.current.trim();

            if (
                finalSpeech &&
                !isLoading &&
                !isSendingRef.current &&
                !voiceCooldownRef.current
            ) {
                voiceCooldownRef.current = true;

                setTimeout(() => {
                    voiceCooldownRef.current = false;
                }, 1500);

                sendToBackendRef.current?.(finalSpeech, selectedImage);
            }
        };

        recognition.onerror = (event) => {
            console.error("Speech Recognition Error:", event.error);

            if (event.error === "no-speech") {
                if (!transcriptRef.current.trim()) {
                    alert("No speech detected. Please try again");
                }
            }

            setIsListening(false);
        };

        recognition.onresult = (event) => {
            if (isLoading || isSendingRef.current || voiceCooldownRef.current) return;

            let completeTranscript = "";
            for (let i = 0; i < event.results.length; ++i) {
                completeTranscript += event.results[i][0].transcript;
            }

            transcriptRef.current = completeTranscript;
            setMessage(completeTranscript);

            // Reset the silence timeout
            if (voiceTimeoutRef.current) {
                clearTimeout(voiceTimeoutRef.current);
            }
            voiceTimeoutRef.current = setTimeout(() => {
                recognition.stop();
            }, 1500); // Stop listening after 1.5 seconds of silence
        };

        recognitionRef.current = recognition;

        return () => {
            if (recognitionRef.current) {
                recognitionRef.current.stop();
            }
            if (voiceTimeoutRef.current) {
                clearTimeout(voiceTimeoutRef.current);
            }
        };
    }, [isLoading, selectedImage]);


    const startListening = () => {
        if (!recognitionRef.current) {
            alert("Speech Recognition is not supported in this browser.");
            return;
        }

        if (isListening || isLoading || isSendingRef.current) return;

        transcriptRef.current = "";
        setMessage("");
        recognitionRef.current.start();
    };

    const stopListening = () => {
        if (recognitionRef.current && isListening) {
            recognitionRef.current.stop();
        }
    };

    const sendMessage = async (e) => {
        if (e) e.preventDefault();
        if ((!message.trim() && !selectedImage) || isLoading || isSendingRef.current) return;
        await sendToBackendRef.current?.(message, selectedImage);
    };

    const sendToBackend = useCallback(async (text, image) => {
        const token = sessionStorage.getItem("token");

        if (!token) {
            alert("Please login first");
            return;
        }
        if (isSendingRef.current) return;
        isSendingRef.current = true;

        const userMessage = (text || "").trim();
        setChat(prev => [
            ...prev,
            { sender: "user", text: userMessage || "📷 Image Uploaded" }
        ]);

        setMessage("");
        setIsLoading(true);

        try {
            const formData = new FormData();
            formData.append("message", userMessage);
            if (image) {
                formData.append("image", image, image.name);
            }
            const response = await API.post(
                `/chat`,
                formData,
                {
                    headers: {
                        "Content-Type": "multipart/form-data"
                    },
                    timeout: 180000,
                }
            );

            if (response.data && response.data.reply) {
                const aiReply = response.data.reply;
                setChat(prev => [
                    ...prev,
                    {
                        sender: "ai",
                        text: aiReply
                    }
                ]);
                speakText(aiReply);

                // Sync dashboard after reminder/note actions
                const dbUpdated = response.data.db_updated;
                if (dbUpdated) {
                    fetchDashboard();
                }
            } else {
                throw new Error("Invalid response format from server");
            }
        } catch (error) {
            console.error("Chat Error:", error);

            let errorText = "Unable to reach the AI assistant. Please check if the backend server is running.";

            if (error.code === "ECONNABORTED") {
                errorText = "The request timed out. The server took too long to respond.";
            } else if (error.response && error.response.data && error.response.data.detail) {
                errorText = `Error: ${error.response.data.detail}`;
            } else if (error.response && error.response.data && error.response.data.reply) {
                errorText = error.response.data.reply;
            }

            setChat(prev => [
                ...prev,
                {
                    sender: "ai",
                    text: errorText,
                    isError: true
                }
            ]);
        } finally {
            setIsLoading(false);
            setSelectedImage(null);
            if (fileInputRef.current) {
                fileInputRef.current.value = "";
            }
            isSendingRef.current = false;
        }
    }, [selectedImage, fetchDashboard, speakText]);
    useEffect(() => {
        sendToBackendRef.current = sendToBackend;
    }, [sendToBackend]);

    return (
        <div className="container">
            <div className="top-bar">
                <div className="brand">
                    <h1>AI Personal Assistant</h1>
                    <p className="welcome-text">Welcome, {userName}</p>
                </div>
                <button onClick={handleLogout} className="logout-btn">
                    🚪 Logout
                </button>
            </div>
            <div className="chat-box">
                {chat.map((msg, index) => (
                    <div
                        key={index}
                        className={`${msg.sender === "user" ? "user-message" : "ai-message"
                            } ${msg.isError ? "error-message" : ""}`}
                    >
                        <strong>{msg.sender === "user" ? "You" : "AI Assistant"}:</strong>
                        {typeof msg.text === "string" ? (msg.text) : (
                            <div className="ai-card">
                                <h3>{msg.text.title || "AI Assistant"}</h3>
                                <p>{msg.text.summary || "No response details provided."}</p>
                                {msg.text.details && msg.text.details.length > 0 && (
                                    <ul>
                                        {msg.text.details.map((item, i) => (
                                            <li key={i}>{item}</li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        )}
                    </div>
                ))}

                {isLoading && (
                    <div className="ai-message typing-indicator">
                        <strong>AI Assistant:</strong> <span>Typing...</span>
                    </div>
                )}

                {isListening && (
                    <div className="ai-message">
                        🎤 Listening...
                    </div>
                )}

                <div ref={chatEndRef} />
            </div>

            <form onSubmit={sendMessage} className="input-area">
                <input
                    type="text"
                    placeholder={isLoading ? "AI is thinking..." : "Type your message..."}
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    disabled={isLoading}
                />
                <button type="submit" disabled={(!selectedImage && !message.trim()) || isLoading}>
                    {isLoading ? "Sending..." : "Send"}
                </button>
                <button
                    type="button"
                    onClick={isListening ? stopListening : startListening}
                    className={isListening ? "mic-active" : ""}
                    title={isListening ? "Stop listening" : "Start listening"}
                >
                    🎤
                </button>
                <button type="button" onClick={() => setIsMuted(!isMuted)}>
                    {isMuted ? "🔇 Unmute" : "🔊 Mute"}
                </button>
                <input ref={fileInputRef} type="file" accept="image/*" onChange={(e) => setSelectedImage(e.target.files[0])} />
            </form>

            {/* Dashboard Message */}
            {dashboardMsg && (
                <div className="dashboard-msg">{dashboardMsg}</div>
            )}

            {/* Productivity Dashboard */}
            <div className="dashboard">
                <h2 className="dashboard-title">📋 Productivity Dashboard</h2>

                {dashboardLoading && <div className="dashboard-loading">Loading...</div>}

                <div className="dashboard-grid">
                    {/* Reminders Panel */}
                    <div className="dashboard-panel">
                        <div className="panel-header">
                            <h3>⏰ Reminders</h3>
                            <span className="badge">{reminders.length}</span>
                        </div>
                        {reminders.length === 0 ? (
                            <p className="empty-text">No reminders yet. Try saying "remind me to drink water at 7"</p>
                        ) : (
                            <ul className="dashboard-list">
                                {reminders.map((r) => (
                                    <li key={r.id} className="dashboard-item">
                                        {editingReminder === r.id ? (
                                            <div className="edit-form">
                                                <input
                                                    type="text"
                                                    value={editReminderText}
                                                    onChange={(e) => setEditReminderText(e.target.value)}
                                                    placeholder="Reminder text"
                                                    className="edit-input"
                                                />
                                                <input
                                                    type="text"
                                                    value={editReminderTime}
                                                    onChange={(e) => setEditReminderTime(e.target.value)}
                                                    placeholder="Time"
                                                    className="edit-input"
                                                />
                                                <select
                                                    value={editReminderRepeat}
                                                    onChange={(e) =>
                                                        setEditReminderRepeat(e.target.value)
                                                    }
                                                >
                                                    <option value="none">One Time</option>
                                                    <option value="daily">Daily</option>
                                                    <option value="weekly">Weekly</option>
                                                    <option value="monthly">Monthly</option>
                                                </select>
                                                <div className="edit-actions">
                                                    <button className="btn-save" onClick={() => saveEditReminder(r.id)}>Save</button>
                                                    <button className="btn-cancel" onClick={cancelEditReminder}>Cancel</button>
                                                </div>
                                            </div>
                                        ) : (
                                            <>
                                                <div className="item-content">
                                                    <span className="item-text">{r.text}</span>
                                                    <span className="item-time">
                                                        {r.time}
                                                        {r.date && (
                                                            <span style={{ marginLeft: "8px", opacity: 0.85, fontStyle: "italic" }}>
                                                                ({r.date})
                                                            </span>
                                                        )}
                                                        {r.repeat_type && r.repeat_type !== "none" && (
                                                            <span
                                                                style={{
                                                                    marginLeft: "8px",
                                                                    color: "#2196f3",
                                                                    fontWeight: "bold"
                                                                }}
                                                            >
                                                                🔁 Repeats {r.repeat_type}
                                                            </span>
                                                        )}
                                                    </span>
                                                </div>
                                                <div className="item-actions">
                                                    <button className="btn-edit" onClick={() => startEditReminder(r)}>✏️</button>
                                                    <button className="btn-delete" onClick={() => handleDeleteReminder(r.id)}>🗑️</button>
                                                </div>
                                            </>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>

                    {/* Notes Panel */}
                    <div className="dashboard-panel">
                        <div className="panel-header">
                            <h3>📝 Notes</h3>
                            <span className="badge">{notes.length}</span>
                        </div>
                        {notes.length === 0 ? (
                            <p className="empty-text">No notes yet. Try saying "save note buy groceries"</p>
                        ) : (
                            <ul className="dashboard-list">
                                {notes.map((n) => (
                                    <li key={n.id} className="dashboard-item">
                                        {editingNote === n.id ? (
                                            <div className="edit-form">
                                                <textarea
                                                    value={editNoteContent}
                                                    onChange={(e) => setEditNoteContent(e.target.value)}
                                                    placeholder="Note content"
                                                    className="edit-textarea"
                                                />
                                                <div className="edit-actions">
                                                    <button className="btn-save" onClick={() => saveEditNote(n.id)}>Save</button>
                                                    <button className="btn-cancel" onClick={cancelEditNote}>Cancel</button>
                                                </div>
                                            </div>
                                        ) : (
                                            <>
                                                <div className="item-content">
                                                    <span className="item-text">{n.content}</span>
                                                </div>
                                                <div className="item-actions">
                                                    <button className="btn-edit" onClick={() => startEditNote(n)}>✏️</button>
                                                    <button className="btn-delete" onClick={() => handleDeleteNote(n.id)}>🗑️</button>
                                                </div>
                                            </>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
