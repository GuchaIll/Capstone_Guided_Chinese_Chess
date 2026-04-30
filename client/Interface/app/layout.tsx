import type { Metadata } from 'next';
import Script from 'next/script';
import '../src/index.css';

export const metadata: Metadata = {
  title: 'Chinese Chess Engine',
};

// Tailwind via CDN. The previous Vite setup loaded this from index.html;
// migrating to a build-time Tailwind toolchain is its own refactor and
// out of scope for this turn — keep the same wire shape so the visual
// design stays pixel-identical.
const TAILWIND_CONFIG = `
  tailwind.config = {
    darkMode: "class",
    theme: {
      extend: {
        colors: {
          "primary": "#137fec",
          "background-light": "#f6f7f8",
          "background-dark": "#0a0f14",
        },
        fontFamily: { "display": ["Space Grotesk"] },
      },
    },
  };
`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/icon?family=Material+Icons"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
          rel="stylesheet"
        />
        <Script
          src="https://cdn.tailwindcss.com?plugins=forms,container-queries"
          strategy="beforeInteractive"
        />
        <Script id="tailwind-config" strategy="beforeInteractive">
          {TAILWIND_CONFIG}
        </Script>
      </head>
      <body>{children}</body>
    </html>
  );
}
