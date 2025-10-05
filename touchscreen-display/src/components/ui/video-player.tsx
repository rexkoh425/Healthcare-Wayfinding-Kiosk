import {
  useEffect,
  useRef,
  useState,
  forwardRef,
  useImperativeHandle,
} from "react";
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize,
  SkipBack,
  SkipForward,
} from "lucide-react";
import { Chapter } from "@/types/video";

interface VideoPlayerProps {
  src: string;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  onTimeUpdate: (currentTime: number) => void;
  onChapterChange: (chapter: Chapter) => void;
}

export interface VideoPlayerHandle {
  seek: (time: number) => void;
}

const VideoPlayer = forwardRef<VideoPlayerHandle, VideoPlayerProps>(
  ({ src, chapters, currentChapter, onTimeUpdate, onChapterChange }, ref) => {
    const videoRef = useRef<HTMLVideoElement>(null);
    const [isPlaying, setIsPlaying] = useState(false);
    const [isMuted, setIsMuted] = useState(false);
    const [volume, setVolume] = useState(1);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [showControls, setShowControls] = useState(true);

    // expose a seek() method to parent
    useImperativeHandle(
      ref,
      () => ({
        seek: (time: number) => {
          const video = videoRef.current;
          if (!video) return;
          video.currentTime = time;
          video.play();
          setIsPlaying(true);
        },
      }),
      []
    );

    // Whenever parent tells us the chapter changed, seek the video
    useEffect(() => {
      const video = videoRef.current;
      if (video && currentChapter) {
        video.currentTime = currentChapter.startTime;
        // auto-play once you seek
        video.play();
      }
    }, [currentChapter]);

    useEffect(() => {
      const video = videoRef.current;
      if (!video) return;

      const handleTimeUpdate = () => {
        setCurrentTime(video.currentTime);
        onTimeUpdate(video.currentTime);
      };

      const handleLoadedMetadata = () => {
        setDuration(video.duration);
      };

      video.addEventListener("timeupdate", handleTimeUpdate);
      video.addEventListener("loadedmetadata", handleLoadedMetadata);

      return () => {
        video.removeEventListener("timeupdate", handleTimeUpdate);
        video.removeEventListener("loadedmetadata", handleLoadedMetadata);
      };
    }, [onTimeUpdate]);

    const togglePlay = () => {
      const video = videoRef.current;
      if (!video) return;

      if (isPlaying) {
        video.pause();
      } else {
        video.play();
      }
      setIsPlaying(!isPlaying);
    };

    const toggleMute = () => {
      const video = videoRef.current;
      if (!video) return;

      video.muted = !isMuted;
      setIsMuted(!isMuted);
    };

    const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const video = videoRef.current;
      if (!video) return;

      const newVolume = parseFloat(e.target.value);
      video.volume = newVolume;
      setVolume(newVolume);
      setIsMuted(newVolume === 0);
    };

    const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
      const video = videoRef.current;
      if (!video) return;

      const newTime = parseFloat(e.target.value);
      video.currentTime = newTime;
      video.play();
      setIsPlaying(true);
      setCurrentTime(newTime);
    };

    const goToPreviousChapter = () => {
      if (!currentChapter) return;

      const currentIndex = chapters.findIndex(
        (ch) => ch.id === currentChapter.id
      );
      if (currentIndex > 0) {
        const prevChapter = chapters[currentIndex - 1];
        seekToChapter(prevChapter);
      }
    };

    const goToNextChapter = () => {
      if (!currentChapter) return;

      const currentIndex = chapters.findIndex(
        (ch) => ch.id === currentChapter.id
      );
      if (currentIndex < chapters.length - 1) {
        const nextChapter = chapters[currentIndex + 1];
        seekToChapter(nextChapter);
      }
    };

    const seekToChapter = (chapter: Chapter) => {
      const video = videoRef.current;
      if (!video) return;

      video.currentTime = chapter.startTime;
      video.play();
      setIsPlaying(true);
      onChapterChange(chapter);
    };

    const toggleFullscreen = () => {
      const video = videoRef.current;
      if (!video) return;

      if (document.fullscreenElement) {
        document.exitFullscreen();
      } else {
        video.requestFullscreen();
      }
    };

    const formatTime = (time: number) => {
      const minutes = Math.floor(time / 60);
      const seconds = Math.floor(time % 60);
      return `${minutes}:${seconds.toString().padStart(2, "0")}`;
    };

    return (
      <div
        className="relative bg-black rounded-lg overflow-hidden shadow-2xl"
        onMouseEnter={() => setShowControls(true)}
        onMouseLeave={() => setShowControls(false)}
      >
        <video
          ref={videoRef}
          src={src}
          className="w-full h-auto max-h-[60vh] object-contain"
          onClick={togglePlay}
        />

        {/* Controls Overlay */}
        <div
          className={`absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-4 transition-opacity duration-300 ${
            showControls ? "opacity-100" : "opacity-0"
          }`}
        >
          {/* Progress Bar */}
          <div className="mb-4">
            <input
              type="range"
              min="0"
              max={duration}
              value={currentTime}
              onChange={handleSeek}
              className="w-full h-1 bg-white/30 rounded-lg appearance-none cursor-pointer slider"
              style={{
                background: `linear-gradient(to right, hsl(var(--primary)) 0%, hsl(var(--primary)) ${(currentTime / duration) * 100}%, rgba(255,255,255,0.3) ${(currentTime / duration) * 100}%, rgba(255,255,255,0.3) 100%)`,
              }}
            />
          </div>

          {/* Controls */}
          <div className="flex items-center justify-between text-white">
            <div className="flex items-center space-x-4">
              <button
                onClick={goToPreviousChapter}
                className="p-2 hover:bg-white/20 rounded-full transition-colors"
                disabled={
                  !currentChapter ||
                  chapters.findIndex((ch) => ch.id === currentChapter.id) === 0
                }
              >
                <SkipBack size={20} />
              </button>

              <button
                onClick={togglePlay}
                className="p-3 hover:bg-white/20 rounded-full transition-colors"
              >
                {isPlaying ? <Pause size={24} /> : <Play size={24} />}
              </button>

              <button
                onClick={goToNextChapter}
                className="p-2 hover:bg-white/20 rounded-full transition-colors"
                disabled={
                  !currentChapter ||
                  chapters.findIndex((ch) => ch.id === currentChapter.id) ===
                    chapters.length - 1
                }
              >
                <SkipForward size={20} />
              </button>

              <div className="flex items-center space-x-2">
                <button
                  onClick={toggleMute}
                  className="p-2 hover:bg-white/20 rounded-full transition-colors"
                >
                  {isMuted ? <VolumeX size={20} /> : <Volume2 size={20} />}
                </button>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={isMuted ? 0 : volume}
                  onChange={handleVolumeChange}
                  className="w-20 h-1 bg-white/30 rounded-lg appearance-none cursor-pointer"
                />
              </div>
            </div>

            <div className="flex items-center space-x-4">
              <span className="text-sm">
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>
              <button
                onClick={toggleFullscreen}
                className="p-2 hover:bg-white/20 rounded-full transition-colors"
              >
                <Maximize size={20} />
              </button>
            </div>
          </div>
        </div>

        {/* Chapter Title Overlay */}
        {currentChapter && (
          <div className="absolute top-4 left-4 bg-black/70 text-white px-4 py-2 rounded-lg backdrop-blur-sm">
            <h3 className="font-semibold">{currentChapter.title}</h3>
            {currentChapter.description && (
              <p className="text-sm text-white/80">
                {currentChapter.description}
              </p>
            )}
          </div>
        )}
      </div>
    );
  }
);

export default VideoPlayer;
