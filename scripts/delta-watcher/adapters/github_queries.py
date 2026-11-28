"""GraphQL query templates used by GitHubTrackerAdapter.

Kept separate from adapter control flow so query shapes stay concise and easy to audit
against GitHub GraphQL schema changes.
"""
from __future__ import annotations

OPEN_ISSUES_QUERY = """
query($owner: String!, $name: String!, $cursor: String, $labels: [String!]) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, labels: $labels, first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        number
        title
        body
        state
        url
        updatedAt
        authorAssociation
        author { login }
        labels(first: 25) { nodes { name } }
        comments(last: 20) {
          nodes {
            id
            body
            url
            createdAt
            authorAssociation
            author { login }
          }
        }
      }
    }
  }
}
"""

OPEN_PRS_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        body
        state
        url
        updatedAt
        reviewDecision
        authorAssociation
        author { login }
        closingIssuesReferences(first: 10) { nodes { number } }
        commits(last: 1) {
          nodes { commit { statusCheckRollup { state } } }
        }
        comments(last: 20) {
          nodes {
            id
            body
            url
            createdAt
            authorAssociation
            author { login }
          }
        }
      }
    }
  }
}
"""


def build_open_issues_by_numbers_query(numbers: list[int]) -> str:
    """Builds one aliased GraphQL batch query fetching tracked issues by number regardless of labels."""
    aliases = "\n".join(
        f"""i{n}: issueOrPullRequest(number: {n}) {{ ... on Issue {{
          id number title body state url updatedAt authorAssociation
          author {{ login }}
          labels(first: 25) {{ nodes {{ name }} }}
          comments(last: 20) {{ nodes {{ id body url createdAt authorAssociation author {{ login }} }} }}
        }} }}"""
        for n in numbers
    )
    return f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {aliases} }} }}"


def build_closed_items_query(numbers: list[int]) -> str:
    """Builds one aliased GraphQL batch query checking closed states for dependency numbers."""
    aliases = "\n".join(
        f"i{n}: issueOrPullRequest(number: {n}) {{ ... on Issue {{ number state }} }}"
        for n in numbers
    )
    return f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {aliases} }} }}"
