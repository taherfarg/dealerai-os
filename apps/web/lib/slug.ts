/** A workspace address from its name — `^[a-z0-9][a-z0-9-]*$`, 60 at most, as
 *  the API requires. Empty when the name has no Latin letters to borrow. */
export function slugFrom(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/, "");
}
