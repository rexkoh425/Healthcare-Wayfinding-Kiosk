export interface Chapter {
  id: number;
  title: string;
  startTime: number;
  endTime: number;
  thumbnail: string;
  description?: string;
}

export interface VideoPlayerProps {
  src: string;
  chapters: Chapter[];
  onChapterChange?: (chapter: Chapter) => void;
}