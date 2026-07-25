import { useState } from "react";
import type { SpeciesImage } from "../lib/api/schemas";

// R3: an image is shown only WITH a visible licence + attribution. If the image is
// missing or fails to load, we degrade gracefully to a labelled placeholder (never a
// broken-image icon). Production supplies verified, licensed photographs.
export function AttributedImage({ image, name }: { image?: SpeciesImage; name: string }) {
  const [failed, setFailed] = useState(false);
  if (!image || failed) {
    return (
      <div className="attr-fallback" role="img" aria-label={`No photograph is currently available for ${name}.`}>
        Photograph pending licence
      </div>
    );
  }
  return (
    <figure className="attr-fig">
      <img src={image.url} alt={image.alt} width={640} height={427} loading="lazy" onError={() => setFailed(true)} />
      <figcaption className="attr-cap">
        © {image.author} ·{" "}
        <a href={image.licenceUrl} target="_blank" rel="noreferrer noopener">
          {image.licence}
        </a>{" "}
        ·{" "}
        <a href={image.sourceUrl} target="_blank" rel="noreferrer noopener">
          source
        </a>
      </figcaption>
    </figure>
  );
}
