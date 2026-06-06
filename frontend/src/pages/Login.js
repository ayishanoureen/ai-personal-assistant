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
            sessionStorage.setItem("userName", user.displayName)
            await API.post(
                "/save-profile",
                {
                    name: user.displayName
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
        <div className="login-container">
            <h1>AI Assistant Login</h1>
            <button onClick={handleLogin}>
                🔐 Login with Google
            </button>
        </div>
    );
}