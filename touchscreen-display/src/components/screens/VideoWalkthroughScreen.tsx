import { useEffect, useState, useRef } from "react";
import { Button } from "@/components/ui/button";
import VideoPlayer from "@/components/ui/video-player";
import type { VideoPlayerHandle } from "@/components/ui/video-player";
import ChapterTimeline from "@/components/ui/chapter-timeline";
import { Chapter } from "@/types/video";
import { Map } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

const VideoWalkthroughScreen: React.FC = () => {
  const router = useRouter();
  const { t } = useTranslation();

  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [currentChapter, setCurrentChapter] = useState<Chapter | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const playerRef = useRef<VideoPlayerHandle>(null);

  // Initialise chapters data
  useEffect(() => {
    const chaptersData: Chapter[] = [
      {
        id: 1,
        title: "Starting Point",
        startTime: 0,
        endTime: 9,
        thumbnail: "/videos/route-2/chapters/[1] Teaching Cluster (Kiosk).png",
        description: "Begin your journey at the main entrance",
      },
      {
        id: 2,
        title: "Yellow Ceiling",
        startTime: 9,
        endTime: 16,
        thumbnail: "/videos/route-2/chapters/[2] Yellow Ceiling.png",
        description: "Turn right to the lift lobby",
      },
      {
        id: 3,
        title: "E2-3 Lift",
        startTime: 16,
        endTime: 34,
        thumbnail: "/videos/route-2/chapters/[3] E2-3 Lift.png",
        description: "Take the lift up",
      },
      {
        id: 4,
        title: "Techhub Door",
        startTime: 34,
        endTime: 46,
        thumbnail: "/videos/route-2/chapters/[4] Techhub Door.png",
        description: "Enter Techhub",
      },
      {
        id: 5,
        title: "Firehose",
        startTime: 46,
        endTime: 48,
        thumbnail: "/videos/route-2/chapters/[5] Firehose.png",
        description: "Walk past the firehose",
      },
      {
        id: 6,
        title: "E2A Door",
        startTime: 48,
        endTime: 62,
        thumbnail: "/videos/route-2/chapters/[6] E2 Door.png",
        description: "Enter E2A",
      },
      {
        id: 7,
        title: "E2A-1 Lift Level 2",
        startTime: 62,
        endTime: 81,
        thumbnail:
          "/videos/route-2/chapters/[7] E2A-1 Lift Level 2 (Kiosk).png",
        description: "Go one level up",
      },
      {
        id: 8,
        title: "Destination: E2A Studio 3",
        startTime: 81,
        endTime: 82,
        thumbnail: "/videos/route-2/chapters/[8] E2A Studio 3.png",
        description: "You have arrived at your destination",
      },
    ];

    setChapters(chaptersData);
    setCurrentChapter(chaptersData[0]);
  }, []);

  // Update current chapter based on video time
  const handleTimeUpdate = (time: number) => {
    setCurrentTime(time);

    const activeChapter = chapters.find(
      (chapter) => time >= chapter.startTime && time < chapter.endTime
    );

    if (activeChapter && activeChapter.id !== currentChapter?.id) {
      setCurrentChapter(activeChapter);
    }
  };

  const handleChapterClick = (chapter: Chapter) => {
    setCurrentChapter(chapter);
  };

  // when the timeline bar is clicked we get a time -> seek the player
  const handleProgressClick = (time: number) => {
    setCurrentTime(time);
    if (playerRef.current) {
      playerRef.current.seek(time);
    }
  };

  return (
    <div className="min-h-screen bg-background p-4 sm:p-6 lg:p-8">
      <div className="max-w-7xl mx-auto">
        {/* --- Map Navigation Block --- */}
        <div className="mb-6 flex items-center space-x-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              (window.location.href =
                "https://3301-map-rex-kohs-projects.vercel.app/")
            }
            className="p-2 rounded-full shadow bg-white hover:text-hospital-blue-gray hover:bg-hospital-blue/5"
          >
            <Map size={20} className="text-hospital-teal" />
          </Button>
          <p className="text-sm text-muted-foreground">
            {t(
              "video.mapNavigationText",
              "Switch to an interactive map view of this route"
            )}
          </p>
        </div>

        {/* Header */}
        <div className="mb-8">
          <p className="text-muted-foreground">{t("video.description")}</p>
        </div>

        {/* Video Player */}
        <div className="mb-8">
          <VideoPlayer
            ref={playerRef}
            src="/videos/route-2/Route_2.mp4"
            chapters={chapters}
            currentChapter={currentChapter}
            onTimeUpdate={handleTimeUpdate}
            onChapterChange={handleChapterClick}
          />
        </div>

        {/* Chapter Timeline */}
        <ChapterTimeline
          chapters={chapters}
          currentChapter={currentChapter}
          currentTime={currentTime}
          duration={82} // 1.22 minutes total
          onChapterClick={handleChapterClick}
          onProgressClick={handleProgressClick}
        />

        {/* Additional Info */}
        <div className="mt-8 p-6 bg-card rounded-lg border">
          <h3 className="text-lg font-semibold mb-3">
            {t("video.tipsHeader")}
          </h3>
          <ul className="space-y-2 text-sm text-muted-foreground">
            <li>- {t("video.tipsPointOne")}</li>
            <li>- {t("video.tipsPointTwo")}</li>
            <li>- {t("video.tipsPointThree")}</li>
            <li>- {t("video.tipsPointFour")}</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default VideoWalkthroughScreen;
