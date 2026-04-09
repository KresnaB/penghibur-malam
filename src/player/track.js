export class Track {
  constructor({
    sourceUrl = "",
    title = "Unknown",
    url = "",
    duration = 0,
    thumbnail = "",
    uploader = "Unknown",
    requester = null,
  }) {
    this.sourceUrl = sourceUrl;
    this.title = title;
    this.url = url;
    this.duration = Number(duration) || 0;
    this.thumbnail = thumbnail;
    this.uploader = uploader;
    this.requester = requester
      ? {
          id: requester.id ?? "0",
          name: requester.username ?? requester.name ?? "Unknown",
          displayName: requester.displayName ?? requester.username ?? requester.name ?? "Unknown",
        }
      : null;
    this.insertId = 0;
  }

  get durationText() {
    if (!this.duration) {
      return "Live";
    }
    const total = Math.max(0, Math.floor(this.duration));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    if (hours) {
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }
}
