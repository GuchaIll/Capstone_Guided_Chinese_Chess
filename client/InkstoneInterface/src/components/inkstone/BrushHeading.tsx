import brushStroke from "../../assets/brush-stroke.png";

interface Props {
  children: React.ReactNode;
  className?: string;
  showBrush?: boolean;
}

export const BrushHeading = ({ children, className = "", showBrush = true }: Props) => {
  return (
    <div className={`relative inline-block ${className}`}>
      <h2 className="font-calligraphy text-ink text-4xl md:text-6xl relative z-10">
        {children}
      </h2>
      {showBrush && (
        <img
          src={brushStroke.src}
          alt=""
          className="absolute -bottom-3 left-0 w-full h-6 opacity-20 animate-brush-reveal pointer-events-none"
          loading="lazy"
          width={800}
          height={512}
        />
      )}
    </div>
  );
};
