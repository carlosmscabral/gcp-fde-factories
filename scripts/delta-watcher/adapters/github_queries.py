"""GraphQL query templates used by GitHubTrackerAdapter.

Kept separate from adapter control flow so query shapes stay concise and easy to audit
against GitHub GraphQL schema changes.
"""
from __future__ import annotations

OPEN_ISSUES_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        number
        title
        body
        state
        url
        updatedAt
        author { login }
        labels(first: 25) { nodes { name } }
        comments(last: 20) {
          nodes {
            id
            body
            url
            createdAt
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
            author { login }
          }
        }
      }
    }
  }
}
"""
