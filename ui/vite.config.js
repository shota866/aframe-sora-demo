// ui/vite.config.js
import basicSsl from '@vitejs/plugin-basic-ssl'
import fs from 'node:fs'

export default {
  plugins: [basicSsl()],
  server: {
    https: false,       // devサーバをHTTPSで起動
    key:  fs.readFileSync('./localhost-key.pem'),
    cert: fs.readFileSync('./localhost.pem'),
    // 必要なら他の設定（port/proxy など）もここに
  },
}

