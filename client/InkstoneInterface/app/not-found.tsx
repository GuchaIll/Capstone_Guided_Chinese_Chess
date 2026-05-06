import Link from 'next/link';

export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[hsl(40,15%,95%)] px-6 text-ink">
      <div className="text-center">
        <h1 className="font-calligraphy mb-4 text-6xl">404</h1>
        <p className="mb-4 text-xl text-ink-light">Oops! Page not found</p>
        <Link href="/" className="underline transition-colors hover:text-black/75">
          Return to Home
        </Link>
      </div>
    </main>
  );
}
