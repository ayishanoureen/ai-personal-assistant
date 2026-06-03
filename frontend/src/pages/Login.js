import React from "react";
import { loginWithGoogle } from "../firebase";
import { useNavigate } from "react-router-dom";

export default function Login() {
    const navigate = useNavigate();

    const handleLogin = async () => {
        try {
            const user = await loginWithGoogle();
            const token = await user.getIdToken();

            localStorage.setItem("token", token);
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