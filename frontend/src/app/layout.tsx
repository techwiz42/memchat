import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Memchat",
  description: "Personal AI assistant with memory",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-white text-gray-900 antialiased">{children}</body>
    </html>
  );
}
