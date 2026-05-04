const defaultTopK = Number.parseInt(import.meta.env.VITE_DEFAULT_TOP_K ?? '5', 10)

export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api',
  defaultTopK: Number.isNaN(defaultTopK) ? 5 : defaultTopK,
}
