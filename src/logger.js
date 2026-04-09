const levels = ["debug", "info", "warn", "error"];

function format(level, scope, message, meta) {
  const timestamp = new Date().toISOString().replace("T", " ").replace("Z", "");
  const payload = meta ? ` ${JSON.stringify(meta)}` : "";
  return `${timestamp} | ${scope.padEnd(20)} | ${level.toUpperCase().padEnd(5)} | ${message}${payload}`;
}

export function createLogger(scope) {
  const logger = {};
  for (const level of levels) {
    logger[level] = (message, meta) => {
      const line = format(level, scope, message, meta);
      if (level === "error") {
        console.error(line);
      } else if (level === "warn") {
        console.warn(line);
      } else {
        console.log(line);
      }
    };
  }
  return logger;
}
