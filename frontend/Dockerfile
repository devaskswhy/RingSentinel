FROM node:22-alpine

WORKDIR /app

# Dependencies are installed as their own layer so source edits do not reinstall.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]
