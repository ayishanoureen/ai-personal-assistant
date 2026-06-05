import { createContext, useContext, useState, useEffect } from "react";
const AuthContext = createContect();
export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    useEffect(() => {
        const token = sessionStorage.getItem("token");
        if (token) {
            setUser({ token });
        }
        setLoading(false);
    }, []);

    const login = (token) => {
        sessionStorage.setItem("token", token);
        setUser({ token });
    };

    const logout = () => {
        sessionStorage.removeItem("token");
        setUser(null);
    }

    return (
        <AuthContext.Provider value={{ user, login, logout, loading }}>
            {children}
        </AuthContext.Provider>
    );
}

export const useAuth = () => useContext(AuthContext)