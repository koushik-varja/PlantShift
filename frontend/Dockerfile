FROM node:22.12.0-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
COPY . .
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build
FROM nginx:1.27.3-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
