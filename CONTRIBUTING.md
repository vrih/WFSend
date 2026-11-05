# Contributing

Thanks for helping. The site is for parents and carers in Waltham Forest
first, so accuracy and plain English matter more than anything else.

## Report a mistake or suggest a document

[Open an issue](https://github.com/vrih/WFSend/issues/new/choose) or email
info@wfsenddata.org.uk. Please include:

- the page and figure you mean
- a link to the public document or data set, with a page number if you can

Every figure on the site has to link to a public source, so a document that
isn't published can't be used.

## Change the code or data

Read the [README](README.md) first. It explains where each figure comes
from and how the data is refreshed. [CLAUDE.md](CLAUDE.md) has the house
rules, which apply to people too. The most important ones:

- Every figure links to a public source, on the publisher's own website.
- Copy values exactly as published. Don't round or tidy them.
- Say what the data can and can't show. Don't speculate about causes.
- Write in plain English, following GOV.UK style.
- Pages must work without JavaScript and meet WCAG 2.2 AA.

Before opening a pull request, check the site builds and look at the pages
you changed:

```sh
pip install -r requirements.txt
python scripts/build.py
python -m http.server -d _site
```

Keep one change per pull request, and say which issue it closes.

## Licence

By contributing you agree that your code is released under the MIT licence
and your content and data under the Open Government Licence v3.0, as set out
in [LICENSE](LICENSE).
