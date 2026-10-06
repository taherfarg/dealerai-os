import { Readex_Pro } from "next/font/google";

/**
 * One family for Latin and Arabic ([11] § 3.2). Next fetches it when it builds
 * and serves it from the app's own address: a browser never asks Google for
 * anything.
 *
 * In a file of its own so that nothing a test imports reaches `next/font`,
 * which only exists inside Next's compiler.
 */
export const readex = Readex_Pro({
  subsets: ["latin", "arabic"],
  display: "swap",
  variable: "--font-readex",
});
