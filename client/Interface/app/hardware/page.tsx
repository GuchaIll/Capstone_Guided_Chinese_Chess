'use client';

import dynamic from 'next/dynamic';

const HardwarePage = dynamic(() => import('../../src/views/HardwarePage'), { ssr: false });

export default function Hardware() {
  return <HardwarePage />;
}
