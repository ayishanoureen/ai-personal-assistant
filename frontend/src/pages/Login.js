import React from "react";
import { loginWithGoogle } from "../firebase";
import { useNavigate } from "react-router-dom";
import API from "../api/axios";

export default function Login() {
    const navigate = useNavigate();

    const handleLogin = async () => {
        try {
            const user = await loginWithGoogle();
            const token = await user.getIdToken(true);

            sessionStorage.setItem("token", token);
            const firstName = user.displayName?.split(" ")[0] || "";
            sessionStorage.setItem("userName", firstName);
            await API.post(
                "/save-profile",
                {
                    name: firstName,
                    email: user.email
                },
                {
                    headers: {
                        Authorization: `Bearer ${token}`
                    }
                }
            );

            localStorage.setItem(
                "lastActivity",
                Date.now().toString()
            );

            navigate("/");
        } catch (err) {
            console.error(err);
            alert("Login failed");
        }
    };

    return (
        <div style={styles.container}>
            <div style={styles.card}>
                <h1 style={styles.title}>AI Assistant Login</h1>
                <p style={styles.subtitles}>Sign in to continue to your dashboard</p>
                <button onClick={handleLogin} style={styles.button}>
                    <span style={styles.icon}>🔐</span>
                    Login with Google
                </button>
            </div>
        </div>
    );
}

const styles = {
    container: {
        height: "100vh",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        background: "linear-gradient(135deg, #0f172a, #1e293b)",
        fontFamily: "Arial, sans-serif"
    },

    card: {
        background: "white",
        padding: "40px",
        borderRadius: "16px",
        boxShadow: "0 10px 30px rgba(0,0,0,0.2)",
        textAlign: "center",
        width: "320px"
    },

    title: {
        marginBottom: "10px",
        fontSize: "22px",
        fontWeight: "bold",
        color: "#111827"
    },

    subtitle: {
        marginBottom: "25px",
        fontSize: "14px",
        color: "#6b7280"
    },

    button: {
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "10px",
        width: "100%",
        padding: "12px",
        backgroundColor: "#4285f4",
        color: "#fff",
        border: "none",
        borderRadius: "10px",
        fontSize: "15px",
        cursor: "pointer",
        transition: "0.3s ease"
    },

    icon: {
        fontSize: "18px"
    }
};