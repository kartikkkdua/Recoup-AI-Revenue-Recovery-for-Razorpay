/** @type {import('next').NextConfig} */
const nextConfig = {
  // Vercel + strict-mode friendly
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/proxy/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
