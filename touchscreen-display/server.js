const next = require('next');
const https = require('https');
const fs = require('fs');

const dev = process.env.NODE_ENV !== 'production';
const app = next({ dev });
const handle = app.getRequestHandler();

app.prepare().then(() => {
  try {
    const key = fs.readFileSync('./key_no_passphrase.pem');
    const cert = fs.readFileSync('./cert.pem');
    
    console.log("Key and Certificate successfully loaded.");
    
    https.createServer({ key, cert }, (req, res) => {
      handle(req, res);
    }).listen(3000, (err) => {
      if (err) throw err;
      console.log('> Ready on https://localhost:3000');
    });
    
  } catch (err) {
    console.error("Error reading key or certificate:", err);
  }
});
