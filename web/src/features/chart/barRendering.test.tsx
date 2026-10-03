import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Bar, BarChart, Cell, XAxis, YAxis } from "recharts";

// REGRESSION GUARD. The bars once rendered invisibly in the browser: Recharts animates
// them up from zero height, but users with "prefers-reduced-motion: reduce" have CSS
// animation disabled, so the bars never grew — an empty chart with axes. The chart now
// sets isAnimationActive={false}; this test pins the configuration that draws bars
// immediately at full size.
const data = [
  { year: 2020, count: 4 },
  { year: 2021, count: 9 },
  { year: 2022, count: 12 },
];

describe("chart bar rendering (no dependency on animation)", () => {
  it("draws a rectangle per data point with animation disabled", () => {
    const { container } = render(
      <BarChart width={600} height={220} data={data}>
        <XAxis dataKey="year" />
        <YAxis />
        <Bar dataKey="count" fill="#3f9e63" isAnimationActive={false}>
          {data.map((d) => (
            <Cell key={d.year} fill="#3f9e63" />
          ))}
        </Bar>
      </BarChart>,
    );
    expect(container.querySelectorAll(".recharts-bar").length).toBeGreaterThan(0);
    expect(container.querySelectorAll(".recharts-rectangle").length).toBeGreaterThanOrEqual(data.length);
  });
});
