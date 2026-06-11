import { useEffect } from "react";
import { getAuth, signOut } from "firebase/auth";

const INACTIVITY_LIMIT = 5 * 1000;

export default function useAutoLogout() {
    useEffect(() => {
        let timeout;

        const logout = async () => {
            const auth = getAuth();
            await signOut(auth);
            sessionStorage.removeItem("token");
            sessionStorage.removeItem("userName");
            localStorage.removeItem("lastActivity");

            window.location.replace("/login");
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