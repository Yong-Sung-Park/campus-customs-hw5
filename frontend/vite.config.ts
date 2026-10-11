import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The board calls the FastAPI backend directly at http://localhost:8000
// (CORS on the backend allows this Vite origin, http://localhost:5173).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Native file events are sometimes missed on Windows; polling is reliable.
    watch: { usePolling: true, interval: 300 },
  },
})
