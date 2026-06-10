import axios from "axios";
import { auth } from "../firebase";

const API = axios.create({
    baseURL: "https://ai-personal-assistant-1-e2iq.onrender.com"
});

// Request interceptor: automatically append the latest token (refreshed if needed)
API.interceptors.request.use(async (config) => {
    let token = null;
    const user = auth.currentUser;
    if (user) {
        try {
            // getIdToken() returns current token, or automatically refreshes if expired
            token = await user.getIdToken();
            sessionStorage.setItem("token", token);
        } catch (err) {
            console.error("Error retrieving fresh token:", err);
        }
    }
    
    if (!token) {
        token = sessionStorage.getItem("token");
    }

    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
}, (error) => {
    return Promise.reject(error);
});

// Response interceptor: automatically refresh token and retry request on 401 token expiration
API.interceptors.response.use(
    (response) => response,
    async (error) => {
        const originalRequest = error.config;
        if (
            error.response &&
            error.response.status === 401 &&
            !originalRequest._retry
        ) {
            originalRequest._retry = true;
            const user = auth.currentUser;
            if (user) {
                try {
                    logger.info("Token expired. Attempting silent token refresh...");
                    // Force refresh the token
                    const token = await user.getIdToken(true);
                    sessionStorage.setItem("token", token);
                    originalRequest.headers.Authorization = `Bearer ${token}`;
                    // Retry the original request with the fresh token
                    return API(originalRequest);
                } catch (refreshError) {
                    console.error("Forced token refresh failed:", refreshError);
                }
            }
        }
        return Promise.reject(error);
    }
);

export default API;