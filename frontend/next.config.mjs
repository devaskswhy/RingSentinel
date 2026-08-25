/** @type {import('next').NextConfig} */
const nextConfig = {
  // Backend base URL is injected at build/run time; see .env.example.
  env: {
    NEXT_PUBLIC_API_BASE_URL:
      process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
