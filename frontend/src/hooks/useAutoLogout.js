import { useEffect } from "react";

const INACTIVITY_LIMIT = 60 * 1000;

export default function useAutoLogout() {
    useEffect(() => {
        let timeout;

        const logout = () => {
            sessionStorage.removeItem("token");
            localStorage.removeItem("lastActivity");

            alert("You have been logged out due to inactivity");

            window.location.href = "/login";
        };

        const resetTimer = () => {
            localStorage.setItem("lastActivity", Date.now().toString());
            clearTimeout(timeout);

            timeout = setTimeout(logout, INACTIVITY_LIMIT);
        };

        const events = ["mousemove", "mousedown", "keypress", "scroll", "touchstart", "click"];

        events.forEach(event => window.addEventListener(event, resetTimer));

        resetTimer();

        return () => {
            clearTimeout(timeout);
            events.forEach(event => window.removeEventListener(event, resetTimer));
        };
    }, []);
}