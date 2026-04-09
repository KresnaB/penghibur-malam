export class QueueManager {
  constructor() {
    this.queue = [];
    this.counter = 0;
  }

  add(track) {
    this.counter += 1;
    track.insertId = this.counter;
    this.queue.push(track);
    return this.queue.length;
  }

  getNext() {
    return this.queue.shift() ?? null;
  }

  peekNext() {
    return this.queue[0] ?? null;
  }

  clear() {
    this.queue = [];
    this.counter = 0;
  }

  remove(index) {
    if (index < 0 || index >= this.queue.length) {
      return null;
    }
    return this.queue.splice(index, 1)[0] ?? null;
  }

  move(sourceIndex, targetIndex) {
    if (sourceIndex < 0 || sourceIndex >= this.queue.length) {
      return null;
    }
    const clampedTarget = Math.max(0, Math.min(targetIndex, this.queue.length - 1));
    const [track] = this.queue.splice(sourceIndex, 1);
    this.queue.splice(clampedTarget, 0, track);
    return track;
  }

  shuffle(mode) {
    if (mode === 0) {
      this.queue.sort((a, b) => a.insertId - b.insertId);
      return;
    }
    if (mode === 1) {
      for (let i = this.queue.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        [this.queue[i], this.queue[j]] = [this.queue[j], this.queue[i]];
      }
      return;
    }
    if (mode === 2 && this.queue.length > 1) {
      for (let round = 0; round < 3; round += 1) {
        const middle = Math.floor(this.queue.length / 2);
        const left = this.queue.slice(0, middle);
        const right = this.queue.slice(middle);
        const mixed = [];
        while (left.length || right.length) {
          if (left.length) mixed.push(left.shift());
          if (right.length) mixed.push(right.shift());
        }
        this.queue = mixed;
      }
    }
  }

  putFront(track) {
    this.queue.unshift(track);
  }

  putBack(track) {
    this.queue.push(track);
  }

  prune(predicate) {
    const kept = [];
    const removed = [];
    for (const track of this.queue) {
      try {
        if (predicate(track)) {
          kept.push(track);
        } else {
          removed.push(track);
        }
      } catch {
        removed.push(track);
      }
    }
    this.queue = kept;
    return removed;
  }

  asList(limit = 20) {
    return this.queue.slice(0, limit);
  }

  get size() {
    return this.queue.length;
  }

  get isEmpty() {
    return this.queue.length === 0;
  }
}
