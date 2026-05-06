'use client';

import { useRouter } from 'next/navigation';
import LandingPage from '../../src/views/LandingPage';

export default function HomeAliasPage() {
  const router = useRouter();

  return (
    <LandingPage
      onPlay={() => {
        window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
        router.push('/play');
      }}
    />
  );
}
