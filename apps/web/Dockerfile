FROM node:20-alpine AS base

WORKDIR /app

COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm install

COPY apps/web/ ./

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["npm", "run", "dev"]
