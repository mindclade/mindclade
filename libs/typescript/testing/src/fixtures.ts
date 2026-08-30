export const FIXTURE_EPOCH_MILLIS = 1_777_550_400_000;
export const fixedClock = (): Readonly<{ now: () => number }> => Object.freeze({ now: () => FIXTURE_EPOCH_MILLIS });
export const sequence = <T>(values: readonly T[]): (() => T) => { let index = 0; return () => { if (index >= values.length) throw new Error("fixture sequence exhausted"); return values[index++]!; }; };
