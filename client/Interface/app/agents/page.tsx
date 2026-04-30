'use client';

import dynamic from 'next/dynamic';

const AgentsPage = dynamic(() => import('../../src/views/AgentsPage'), { ssr: false });

export default function Agents() {
  return <AgentsPage />;
}
