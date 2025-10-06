FROM node:20

WORKDIR /app

# only copy package files to leverage Docker cache
COPY package*.json ./
RUN npm install

# copy the rest of your source
COPY . .

EXPOSE 8080
CMD ["npm", "run", "start"]