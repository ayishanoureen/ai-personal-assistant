// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { signInWithPopup, GoogleAuthProvider } from "firebase/auth";
// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
    apiKey: "AIzaSyBInokVRtKdwAcN-hvJTeEXorSiUj-7Y_E",
    authDomain: "ai-assistant-8ce68.firebaseapp.com",
    projectId: "ai-assistant-8ce68",
    storageBucket: "ai-assistant-8ce68.firebasestorage.app",
    messagingSenderId: "172424984947",
    appId: "1:172424984947:web:cd94955ddae225261a2d06",
    measurementId: "G-2VY98WSNBM"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);

export const provider = new GoogleAuthProvider();
export const loginWithGoogle = async () => {
    const result = await signInWithPopup(auth, provider);
    return result.user;
};