import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
  },
  build: {
    // The only chunk above 500 kB is three.js, which MapView loads lazily
    // when the 3D viewer is opened.
    chunkSizeWarningLimit: 560,
    rollupOptions: {
      output: {
        // Split rarely-changing vendors from app code so a frontend deploy to
        // sys1 does not invalidate the cached map bundle.
        manualChunks: {
          leaflet: ['leaflet', 'react-leaflet'],
        },
      },
    },
  },
})
