# GitHub Pages

The project homepage is `index.html`, a Jekyll page with its own layout.
`README.md` remains the detailed tool and experiment documentation.
The homepage uses local CSS, a small interaction script, a vector illustration,
and a locally hosted font. Navigation, expandable sections, code, and citation
downloads work without JavaScript. There are no third-party runtime requests,
analytics, or UI dependencies.

## Design direction

The redesign follows the supplied `DESIGN-uber.md` reference. Its core rules
are captured here so maintaining the site does not require that external file:

- Use black text on light surfaces and white text on dark surfaces, including
  links, captions, feedback, and the website credit. Do not use gray text.
- Keep body text and controls at least 16 px. Use spacing and headings for
  hierarchy instead of small, muted labels. Pale neutral surfaces may group
  content; no accent color, gradient, or card shadow.
- Keep only the tool summary, workflow, paper and authors, setup choices, and
  research links. Put detailed requirements and output interpretation in the
  README. Avoid duplicate badges, captions, section labels, and descriptions.
- Inter 700 headings with neutral tracking and sentence case; 400/500 body text
  and controls. Desktop headings use 52/64, 36/44, and 24/32 px size/line-height.
- Pill buttons, 16 px card corners, a 1200 px content width, and 4 px spacing units.
- A light hero, black paper section in the middle, light setup/data sections,
  and black footer. The 4:3 dependency illustration is explanatory artwork,
  not an analysis result or a claim of measured performance.
- A native, inline mobile menu and expandable details keep interactions within
  the page. No full-screen menu, modal, or toast is needed for this project site.
- Use natural sentences, descriptive labels, or separate lines for metadata.
  Avoid decorative inline separators between versions, names, links, and labels.
- Give every research author equal space in paper order, with a portrait above
  their name and a link to their verified homepage when available. Use one
  compact horizontal row: 112 px portraits on desktop and 88 px on mobile,
  with native horizontal scrolling on narrow screens. Keep the
  separate website credit at the bottom, clearly labeled as website authorship.

Inter is the reference's open-source substitute for the proprietary Uber fonts.
The unmodified variable font comes from the
[official Inter v4.1 release source](https://github.com/rsms/inter/tree/v4.1/docs/font-files).
Its SIL Open Font License is distributed in `assets/fonts/OFL.txt`. The original
paper workflow retains its published colors when expanded. Author photographs
also retain their original colors.

## Preview

With Ruby 3.3 and Bundler installed, run from the repository root:

```sh
bundle install
bundle exec jekyll serve --host 127.0.0.1 --port 4000
```

Open `http://127.0.0.1:4000/DepUpdater/`. The `/DepUpdater` prefix matters:
all local asset URLs use Jekyll's `relative_url` filter.
For a build without a server:

```sh
bundle exec jekyll build --strict_front_matter
```

The `Gemfile` pins Jekyll and the plugins to the versions used by the existing
GitHub Pages setup. Commit `Gemfile.lock` when updating site dependencies.
Generated `_site/`, Bundler state, and local gems must not be committed.

## Content and behavior

- `index.html`: homepage structure, accessible landmarks, and native disclosures.
- `assets/css/home.css`: responsive layout, focus styles, reduced-motion support,
  and print styles.
- `assets/js/home.js`: mobile-menu dismissal and clipboard enhancement with
  inline feedback and a manual selection fallback. Copy buttons remain hidden
  without JavaScript; the native menu still works.
- `_data/authors.yml`: ordered author names, verified homepages, local portraits,
  and photo provenance.
- `assets/images/`: dependency illustration, favicon, and locally hosted author
  portraits in `authors/`.
- `assets/fonts/`: locally hosted Inter variable font and its license.
- `assets/depupdater.bib`: the single source for both the displayed citation and
  the downloadable BibTeX. Metadata comes from the paper's DOI.
- `_config.yml`: repository, paper, dataset, development branch, and original
  artifact commit. Reproduction links are pinned independently of publication.

Keep paper claims and development behavior distinct. New CLI options belong in
the `main` instructions. Do not present development results as the
published experiments, invent evaluation scores, or update the artifact pin
merely to deploy the website.

Before publishing, check desktop and narrow mobile layouts, keyboard navigation,
anchor targets, expanded disclosures, copy success and failure feedback,
JavaScript-disabled behavior, and local asset links under `/DepUpdater/`.
Paper, repository, and snapshot links should be checked separately.

## Publication

The public site is <https://marklee131.github.io/DepUpdater/>. The canonical
repository is <https://github.com/MarkLee131/DepUpdater>. Keep `_config.yml`'s
`url` and `repository_url` aligned with these addresses after any repository move.
`main` is the repository default branch. Publish this homepage from its root,
keeping the original
`artifact` branch unchanged. Set the source in **Settings → Pages → Build and
deployment**. A push updates the live site only when the branch is configured
as its publishing source and the Pages deployment succeeds.

The homepage links to the pinned original artifact independently of the
publishing branch. Check the Pages build/deployment result and the live page
after each publication.

The Jekyll exclusions prevent analyzer binaries, database snapshots, generated
analysis output, and Python implementation directories from being copied into
the website. Published result CSVs remain accessible through the pinned GitHub links; paper
figures are served from `assets/images/paper/`.

## Author portraits

Author order follows the paper. Names and photos link to personal homepages when
available; homepage links do not appear in the main navigation. The separate
footer credit identifies the website author.

Rui Lu, Lyuye Zhang, and Kaixuan Li use the photo files supplied by the authors.
Min Zhang and Yixiang Chen use photos downloaded from their faculty profiles.
All portraits are stored unchanged locally, with their provenance recorded in
`_data/authors.yml`, so the site makes no external image requests. CSS controls
the display crop without changing the source files. The two ECNU faculty links
are the profiles linked from the [SEI faculty directory](https://sei.ecnu.edu.cn/33189/list.htm).
Rui Lu's profile link uses the Google Scholar page supplied by the authors. If a photo is unavailable, use a neutral initials placeholder rather
than an unverified portrait of someone with the same name.

When replacing a portrait, update its local file and source URL, then check the
crop on desktop and mobile. Keep every author in the list even when a photo or
homepage is unavailable.

## Social preview

`assets/images/social-preview.png` is the 1280 × 640 PNG used by the homepage's
Open Graph metadata. Its editable source is `docs/design/social-preview.html`; render
at a 1280 × 640 viewport with device scale 1 after the local Inter font loads.
All content stays inside an 80 px margin, and the PNG is under 1 MB.

GitHub repository previews are configured separately from Pages metadata.
Upload this PNG under **Settings → General → Social preview → Edit** in the
repository. See [GitHub's preview instructions](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview).
