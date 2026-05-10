const parsedTopK = Number.parseInt(import.meta.env.VITE_DEFAULT_TOP_K ?? '3', 10)

export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api',
  defaultTopK: Number.isInteger(parsedTopK) && parsedTopK > 0 ? parsedTopK : 3,
}
