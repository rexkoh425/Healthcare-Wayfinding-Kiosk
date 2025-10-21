FROM node:20

WORKDIR /app

# only copy package files to leverage Docker cache
COPY package*.json ./
RUN npm install

# copy the rest of your source
COPY . .

EXPOSE 3000
# CMD ["npm", "run", "dev"]
CMD ["node", "server.js"]