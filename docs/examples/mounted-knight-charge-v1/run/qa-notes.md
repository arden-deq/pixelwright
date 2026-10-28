# Mounted knight charge preview

- Status: **experimental / changes needed**. This is a format sample for the user to judge, not an accepted animation.
- Generation used the host built-in image_gen: one identity-reference call and one charge-strip call. The sprite-gen provider CLI was not used. No paid fallback, provider preference, or authentication change was made.
- The assistant selected the newly generated 2D reference for this preview. It is not user-approved art. No 3D guide was supplied for this format demonstration.
- Canonical sprite-gen prepare, component extraction, pixel-unfake, compose-atlas, preview, inspect and compose-gif were used without replacing those stages. No fixed-width-cut fallback, hand-painted motion, local retiming or post-compose palette repair was used.
- The raw strip's boundary crops remain defects even though the extraction and compose reports return ok. The fourth displayed pose looks smaller than its neighbors.
- The engine reports pitch disagreement, a physical-cap reduction, and last-frame edge pixels. The independent frozen 32-color contract fails: 62 visible colors are present. Seven frames violate the declared 12-physical-pixel safety margin.
- Motion status is unverified. Static inspection is not evidence that the gallop has stable hoof contact or a seamless loop. No independent hoof observations were collected.
