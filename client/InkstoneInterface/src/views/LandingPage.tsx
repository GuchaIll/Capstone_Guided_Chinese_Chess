'use client';

import { useState } from 'react';
import heroMountains from '../assets/hero-mountains.jpg';
import { BrushHeading } from '../components/inkstone/BrushHeading';
import { InkReveal } from '../components/inkstone/InkReveal';

interface LandingPageProps {
  onPlay: () => void;
}

export default function LandingPage({ onPlay }: LandingPageProps) {
  const [transitioning, setTransitioning] = useState(false);

  const handlePlay = () => {
    setTransitioning(true);
    window.setTimeout(() => onPlay(), 600);
  };

  return (
    <div className={`min-h-screen bg-rice-paper transition-all duration-600 ${transitioning ? 'animate-zoom-exit' : 'animate-zoom-enter'}`}>
      <section className="relative h-screen flex flex-col items-center justify-center overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-rice-paper/60 to-rice-paper z-10" />

        <img
          src={heroMountains.src}
          alt="Ink wash mountain landscape"
          className="absolute inset-0 w-full h-full object-cover opacity-40"
          width={1920}
          height={1080}
        />

        <div className="absolute top-1/4 left-0 w-96 h-32 bg-gradient-to-r from-transparent via-rice-paper/40 to-transparent animate-float-mist" />
        <div className="absolute top-1/2 right-0 w-80 h-24 bg-gradient-to-l from-transparent via-rice-paper/30 to-transparent animate-float-mist" style={{ animationDelay: '3s' }} />

        <div className="relative z-20 text-center px-4">
          <InkReveal>
            <h1 className="font-calligraphy text-ink text-7xl md:text-9xl tracking-wider mb-2">
              象棋
            </h1>
          </InkReveal>
          <InkReveal delay={300}>
            <p className="font-serif-cn text-ink-light text-lg md:text-xl tracking-[0.3em] font-light">
              CHINESE CHESS
            </p>
          </InkReveal>
          <InkReveal delay={600}>
            <p className="font-serif-cn text-ink-wash text-sm mt-6 max-w-md mx-auto leading-relaxed font-extralight">
              千年博弈，一局悟道
            </p>
          </InkReveal>
          <InkReveal delay={900}>
            <button
              onClick={handlePlay}
              className="mt-12 px-12 py-3 border border-ink/30 text-ink font-serif-cn text-sm tracking-[0.2em] hover:bg-ink hover:text-rice-paper transition-all duration-500 relative group"
            >
              <span className="relative z-10">开始对弈</span>
              <div className="absolute inset-0 bg-ink/5 group-hover:bg-ink transition-all duration-500" />
            </button>
          </InkReveal>
        </div>

        <InkReveal delay={1200}>
          <div className="absolute bottom-8 z-20 flex flex-col items-center">
            <div className="w-px h-12 bg-gradient-to-b from-ink/40 to-transparent animate-drip" />
          </div>
        </InkReveal>
      </section>

      <section className="py-24 px-4 max-w-4xl mx-auto">
        <InkReveal>
          <BrushHeading>棋道</BrushHeading>
        </InkReveal>
        <InkReveal delay={200}>
          <p className="mt-8 text-ink-light font-serif-cn text-base leading-loose font-light max-w-2xl">
            象棋，又称中国象棋，是一种源于中国的策略棋类游戏。棋盘上楚河汉界分隔两军，
            将帅对峙，车马炮纵横，兵卒步步为营。方寸之间，尽显智慧与谋略。
          </p>
        </InkReveal>

        <div className="grid md:grid-cols-3 gap-12 mt-16">
          {[
            { title: '将', subtitle: 'The General', desc: '统领全局，坐镇九宫' },
            { title: '馬', subtitle: 'The Horse', desc: '日字腾挪，出奇制胜' },
            { title: '砲', subtitle: 'The Cannon', desc: '隔山打牛，远程克敌' },
          ].map((piece, i) => (
            <InkReveal key={piece.title} delay={i * 200}>
              <div className="text-center group cursor-default">
                <span className="font-calligraphy text-6xl text-ink/80 group-hover:text-ink transition-colors duration-500">
                  {piece.title}
                </span>
                <p className="text-ink-wash text-xs tracking-[0.3em] mt-2 uppercase">{piece.subtitle}</p>
                <p className="text-ink-light text-sm mt-3 font-light">{piece.desc}</p>
              </div>
            </InkReveal>
          ))}
        </div>
      </section>

      <section className="py-24 text-center relative overflow-hidden">
        <div className="absolute inset-0 opacity-10">
          <img src={heroMountains.src} alt="" className="w-full h-full object-cover" loading="lazy" width={1920} height={1080} />
        </div>
        <InkReveal>
          <BrushHeading>对弈</BrushHeading>
        </InkReveal>
        <InkReveal delay={200}>
          <p className="mt-6 text-ink-light font-serif-cn text-sm tracking-wider font-light">
            执子落盘，胜负在此一举
          </p>
        </InkReveal>
        <InkReveal delay={400}>
          <button
            onClick={handlePlay}
            className="mt-10 px-16 py-4 bg-ink text-rice-paper font-serif-cn text-sm tracking-[0.3em] hover:bg-ink/80 transition-all duration-500"
          >
            进入棋局
          </button>
        </InkReveal>
      </section>

      <footer className="py-8 text-center border-t border-ink/10">
        <p className="text-ink-wash text-xs tracking-[0.2em] font-light">水墨象棋 · SHUIMO XIANGQI</p>
      </footer>
    </div>
  );
}
