FROM node:22-alpine AS builder
WORKDIR /app
ARG VITE_API_BASE_URL=/api
ARG VITE_DEFAULT_TOP_K=3
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_DEFAULT_TOP_K=$VITE_DEFAULT_TOP_K
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
RUN apk add --no-cache wget
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
