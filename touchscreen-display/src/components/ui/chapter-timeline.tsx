import { useState } from "react";
import { Chapter } from "@/types/video";

interface ChapterTimelineProps {
  chapters: Chapter[];
  currentChapter: Chapter | null;
  currentTime: number;
  duration: number;
  onChapterClick: (chapter: Chapter) => void;
  onProgressClick?: (time: number) => void;
}

const ChapterTimeline: React.FC<ChapterTimelineProps> = ({
  chapters,
  currentChapter,
  currentTime,
  duration,
  onChapterClick,
  onProgressClick,
}) => {
  const [hoveredChapter, setHoveredChapter] = useState<Chapter | null>(null);

  const getChapterProgress = (chapter: Chapter) => {
    if (currentTime < chapter.startTime) return 0;
    if (currentTime > chapter.endTime) return 100;

    const chapterDuration = chapter.endTime - chapter.startTime;
    const elapsed = currentTime - chapter.startTime;
    return (elapsed / chapterDuration) * 100;
  };

  const formatTime = (time: number) => {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  };

  return (
    <div className="mt-6">
      {/* Timeline Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-foreground">
          Video Chapters
        </h3>
        <div className="text-sm text-muted-foreground">
          {chapters.length} chapters - {formatTime(duration)}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="relative h-2 bg-muted rounded-full mb-6 overflow-hidden">
        <div
          className="relative h-2 bg-muted rounded-full mb-6 overflow-hidden cursor-pointer"
          onClick={(e) => {
            if (!onProgressClick) return;
            const rect = (
              e.currentTarget as HTMLDivElement
            ).getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            const pct = clickX / rect.width;
            const time = pct * duration;
            onProgressClick(time);
          }}
        >
          <div
            className="absolute top-0 left-0 h-full bg-primary rounded-full transition-all duration-300"
            style={{ width: `${(currentTime / duration) * 100}%` }}
          />
          {/* Chapter Markers */}
          {chapters.map((chapter) => (
            <div
              key={chapter.id}
              className="absolute top-0 h-full w-0.5 bg-white/60"
              style={{ left: `${(chapter.startTime / duration) * 100}%` }}
            />
          ))}
        </div>
      </div>

      {/* Chapter Thumbnails */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 gap-3">
        {chapters.map((chapter) => {
          const isActive = currentChapter?.id === chapter.id;
          const isHovered = hoveredChapter?.id === chapter.id;
          const progress = getChapterProgress(chapter);

          return (
            <div
              key={chapter.id}
              className={`group cursor-pointer transition-all duration-300 ${
                isActive ? "ring-2 ring-primary ring-offset-2" : ""
              }`}
              onMouseEnter={() => setHoveredChapter(chapter)}
              onMouseLeave={() => setHoveredChapter(null)}
              onClick={() => onChapterClick(chapter)}
            >
              {/* Thumbnail Container */}
              <div className="relative aspect-video bg-muted rounded-lg overflow-hidden shadow-md">
                <img
                  src={chapter.thumbnail}
                  alt={chapter.title}
                  className={`w-full h-full object-cover transition-transform duration-300 ${
                    isHovered ? "scale-105" : ""
                  }`}
                />

                {/* Progress Overlay */}
                {progress > 0 && (
                  <div className="absolute bottom-0 left-0 right-0 h-1 bg-black/40">
                    <div
                      className="h-full bg-primary transition-all duration-300"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                )}

                {/* Play Overlay */}
                <div
                  className={`absolute inset-0 bg-black/40 flex items-center justify-center transition-opacity duration-300 ${
                    isHovered ? "opacity-100" : "opacity-0"
                  }`}
                >
                  <div className="w-8 h-8 bg-white/90 rounded-full flex items-center justify-center">
                    <div className="w-0 h-0 border-l-[6px] border-l-black border-y-[4px] border-y-transparent ml-0.5" />
                  </div>
                </div>

                {/* Active Indicator */}
                {isActive && (
                  <div className="absolute top-2 right-2 w-3 h-3 bg-primary rounded-full animate-pulse" />
                )}
              </div>

              {/* Chapter Info */}
              <div className="mt-2 space-y-1">
                <h4
                  className={`text-sm font-medium line-clamp-2 transition-colors ${
                    isActive ? "text-primary" : "text-foreground"
                  }`}
                >
                  {chapter.title}
                </h4>
                <p className="text-xs text-muted-foreground">
                  {formatTime(chapter.startTime)}
                </p>
              </div>

              {/* Hover Tooltip */}
              {isHovered && (
                <div className="absolute z-10 bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-2 bg-black/90 text-white text-sm rounded-lg backdrop-blur-sm whitespace-nowrap">
                  <p className="font-medium">{chapter.title}</p>
                  <p className="text-xs opacity-80">
                    {formatTime(chapter.startTime)} -{" "}
                    {formatTime(chapter.endTime)}
                  </p>
                  <div className="absolute top-full left-1/2 transform -translate-x-1/2 border-4 border-transparent border-t-black/90" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default ChapterTimeline;
